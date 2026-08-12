import threading
import uuid
from collections import Counter

import pytest
from django.db import close_old_connections, connections

from apps.orders.models import Order
from apps.organizations.models import Organization
from apps.payments.exceptions import InvalidPayment, VersionConflict
from apps.payments.models import PaymentAttempt, PaymentIntent, PaymentProviderAccount, PaymentWebhookReceipt
from apps.payments.providers import CheckoutResult, ProviderResource
from apps.payments.services import (
    activate_hosted_checkout,
    apply_verified_provider_resource,
    consume_order_cancelled,
    create_payment_intent,
    dispatch_requested_checkout,
    reconcile_verified_resource,
    request_hosted_checkout,
    request_hosted_checkout_cancellation,
)
from apps.payments.tasks import dispatch_checkout_cancellation_events
from apps.users.models import User


@pytest.mark.django_db(transaction=True)
def test_concurrent_checkout_requests_produce_only_one_active_attempt(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    barrier = threading.Barrier(2)
    successes = []
    expected_errors = []
    unexpected_errors = []

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            attempt = request_hosted_checkout(
                organization=Organization.objects.get(id=organization.id),
                intent=PaymentIntent.objects.get(id=intent.id),
                provider_account=PaymentProviderAccount.objects.get(id=mercado_account.id),
                actor=User.objects.get(id=manager.id),
                expected_version=1,
                idempotency_key=str(uuid.uuid4()),
            )
            successes.append(attempt.id)
        except (InvalidPayment, VersionConflict) as exc:
            expected_errors.append(exc)
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected_errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not unexpected_errors
    assert len(successes) == 1
    assert len(expected_errors) == 1
    assert intent.attempts.filter(status="requested").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_intent_creation_produces_one_aggregate(organization, payable_order, manager, manager_membership):
    barrier = threading.Barrier(2)
    outcomes = []

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            created = create_payment_intent(
                organization=Organization.objects.get(id=organization.id),
                order=Order.objects.get(id=payable_order.id),
                actor=User.objects.get(id=manager.id),
                idempotency_key=str(uuid.uuid4()),
            )
            outcomes.append(("created", created.id))
        except InvalidPayment:
            outcomes.append(("rejected", None))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert Counter(outcome for outcome, _ in outcomes) == {"created": 1, "rejected": 1}
    assert PaymentIntent.objects.filter(order=payable_order).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_dispatchers_hold_one_persistent_lease_and_call_provider_once(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
    )
    barrier = threading.Barrier(2)
    calls = []
    outcomes = []
    call_lock = threading.Lock()

    class ConcurrentFakeAdapter:
        provider = "mercado_pago"
        external = False

        def create_checkout(self, checkout_request):
            with call_lock:
                calls.append(checkout_request.idempotency_key)
            return CheckoutResult("concurrent-dispatch", "https://checkout.example.test/concurrent")

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            result = dispatch_requested_checkout(
                attempt=PaymentAttempt.objects.get(id=attempt.id),
                adapter=ConcurrentFakeAdapter(),
                idempotency_key=str(uuid.uuid4()),
            )
            outcomes.append(("active", result.id))
        except InvalidPayment:
            outcomes.append(("rejected", None))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert Counter(outcome for outcome, _ in outcomes) == {"active": 1, "rejected": 1}
    assert calls == [attempt.provider_idempotency_key]
    attempt.refresh_from_db()
    assert attempt.status == PaymentAttempt.Status.ACTIVE
    assert attempt.dispatch_lease_token is None


@pytest.mark.django_db(transaction=True)
def test_concurrent_cancellation_workers_call_provider_once_and_consume_exact_event(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("cancel-concurrent", "https://checkout.example.test/cancel-concurrent"),
        idempotency_key=str(uuid.uuid4()),
    )
    intent.refresh_from_db()
    request_hosted_checkout_cancellation(
        organization=organization,
        intent=intent,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=str(uuid.uuid4()),
    )
    barrier = threading.Barrier(2)
    calls = []
    outcomes = []
    errors = []
    call_lock = threading.Lock()

    class CancellationAdapter:
        provider = "mercado_pago"
        external = False

        def cancel_checkout(self, external_resource_id, *, idempotency_key):
            with call_lock:
                calls.append(external_resource_id)
            return ProviderResource(external_resource_id, "cancelled", 12540, "BRL")

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            outcomes.append(
                dispatch_checkout_cancellation_events(
                    limit=1,
                    adapter_resolver=lambda current: CancellationAdapter(),
                )
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(outcomes) == [0, 1]
    assert calls == ["cancel-concurrent"]
    attempt.refresh_from_db()
    assert attempt.status == PaymentAttempt.Status.CANCELLED
    assert attempt.cancellation_completed_at is not None


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_callbacks_create_one_receipt_and_one_transition(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("callback-race", "https://checkout.example.test/callback-race"),
        idempotency_key=str(uuid.uuid4()),
    )
    barrier = threading.Barrier(2)
    receipt_ids = []
    errors = []

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            receipt = apply_verified_provider_resource(
                provider_account=PaymentProviderAccount.objects.select_related("organization").get(
                    id=mercado_account.id
                ),
                external_event_id="authenticated-event",
                authenticated_request_id_digest="a" * 64,
                request_digest="b" * 64,
                resource=ProviderResource("callback-race", "approved", 12540, "BRL"),
            )
            receipt_ids.append(receipt.id)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(receipt_ids) == 2 and len(set(receipt_ids)) == 1
    assert PaymentWebhookReceipt.objects.filter(provider_account=mercado_account).count() == 1
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.PAID
    assert intent.status_history.filter(to_status=PaymentIntent.Status.PAID).count() == 1


@pytest.mark.django_db(transaction=True)
def test_callback_reconciliation_and_order_cancellation_use_deterministic_locks_without_deadlock(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("lock-order", "https://checkout.example.test/lock-order"),
        idempotency_key=str(uuid.uuid4()),
    )
    intent.refresh_from_db()
    payable_order.status = Order.Status.CANCELLED
    payable_order.cancelled_at = payable_order.confirmed_at
    payable_order.cancel_reason = "Corrida controlada"
    payable_order.save(update_fields=("status", "cancelled_at", "cancel_reason"))
    barrier = threading.Barrier(3)
    errors = []

    def callback_worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            apply_verified_provider_resource(
                provider_account=PaymentProviderAccount.objects.select_related("organization").get(
                    id=mercado_account.id
                ),
                external_event_id="lock-callback",
                authenticated_request_id_digest="c" * 64,
                request_digest="d" * 64,
                resource=ProviderResource("lock-order", "approved", 12540, "BRL"),
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            connections.close_all()

    def reconciliation_worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            reconcile_verified_resource(
                organization=Organization.objects.get(id=organization.id),
                intent=PaymentIntent.objects.get(id=intent.id),
                actor=User.objects.get(id=manager.id),
                expected_version=intent.version,
                idempotency_key=str(uuid.uuid4()),
                resource=ProviderResource("lock-order", "in_process", 12540, "BRL"),
            )
        except VersionConflict:
            pass
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            connections.close_all()

    def cancellation_worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            consume_order_cancelled(
                organization=Organization.objects.get(id=organization.id),
                order_id=payable_order.id,
                source_event_id=uuid.uuid4(),
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=callback_worker),
        threading.Thread(target=reconciliation_worker),
        threading.Thread(target=cancellation_worker),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.REQUIRES_ATTENTION
