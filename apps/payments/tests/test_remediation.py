import socket
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.contrib import admin
from django.utils import timezone

from apps.orders.models import Order
from apps.organizations.models import Membership
from apps.organizations.selectors import ACTIVE_ORGANIZATION_SESSION_KEY
from apps.payments.exceptions import InvalidPayment, OrganizationMismatch, PaymentPermissionDenied
from apps.payments.models import PaymentAttempt, PaymentIntent, PaymentProviderAccount
from apps.payments.providers import CheckoutResult, ProviderResource
from apps.payments.services import (
    DISPATCH_LEASE_SECONDS,
    activate_hosted_checkout,
    claim_requested_checkout,
    consume_order_cancelled,
    create_payment_intent,
    dispatch_requested_checkout,
    fetch_and_reconcile,
    reopen_payment_after_verified_closure,
    request_hosted_checkout,
    request_hosted_checkout_cancellation,
)
from apps.payments.tasks import dispatch_checkout_cancellation_events, dispatch_checkout_events
from apps.platform.models import OutboxEvent
from apps.platform.services import enqueue_event


def key():
    return str(uuid.uuid4())


def create_intent_and_attempt(*, organization, order, account, manager):
    intent = create_payment_intent(
        organization=organization,
        order=order,
        actor=manager,
        idempotency_key=key(),
    )
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=account,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=key(),
    )
    return intent, attempt


@pytest.mark.django_db
def test_dispatch_revalidates_order_and_preserves_result_if_order_changes_during_io(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent, attempt = create_intent_and_attempt(
        organization=organization,
        order=payable_order,
        account=mercado_account,
        manager=manager,
    )

    class CancellingOrderAdapter:
        provider = "mercado_pago"
        external = False

        def create_checkout(self, checkout_request):
            payable_order.status = Order.Status.CANCELLED
            payable_order.cancelled_at = timezone.now()
            payable_order.cancel_reason = "Cancelado durante o dispatch"
            payable_order.save(update_fields=("status", "cancelled_at", "cancel_reason"))
            consume_order_cancelled(
                organization=organization,
                order_id=payable_order.id,
                source_event_id=uuid.uuid4(),
            )
            return CheckoutResult("race-resource", "https://checkout.example.test/race")

    dispatched = dispatch_requested_checkout(
        attempt=attempt,
        adapter=CancellingOrderAdapter(),
        idempotency_key=key(),
    )
    intent.refresh_from_db()
    assert dispatched.status == PaymentAttempt.Status.ACTIVE
    assert dispatched.external_resource_id == "race-resource"
    assert intent.status == PaymentIntent.Status.REQUIRES_ATTENTION
    assert intent.attention_code == "dispatch_context_changed"


@pytest.mark.django_db
def test_dispatch_closes_without_io_when_order_was_already_cancelled(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent, attempt = create_intent_and_attempt(
        organization=organization,
        order=payable_order,
        account=mercado_account,
        manager=manager,
    )
    payable_order.status = Order.Status.CANCELLED
    payable_order.cancelled_at = timezone.now()
    payable_order.cancel_reason = "Cancelado antes do dispatch"
    payable_order.save(update_fields=("status", "cancelled_at", "cancel_reason"))
    calls = 0

    class SpyAdapter:
        provider = "mercado_pago"
        external = False

        def create_checkout(self, checkout_request):
            nonlocal calls
            calls += 1

    with pytest.raises(InvalidPayment, match="inelegível"):
        dispatch_requested_checkout(attempt=attempt, adapter=SpyAdapter(), idempotency_key=key())
    intent.refresh_from_db()
    attempt.refresh_from_db()
    assert calls == 0
    assert intent.status == PaymentIntent.Status.CANCELLED
    assert attempt.status == PaymentAttempt.Status.CANCELLED
    assert attempt.dispatch_error_code == "order_not_confirmed"


@pytest.mark.django_db
def test_dispatch_stops_before_io_when_account_is_inactive_and_preserves_result_if_disabled_during_io(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent, attempt = create_intent_and_attempt(
        organization=organization,
        order=payable_order,
        account=mercado_account,
        manager=manager,
    )
    mercado_account.is_active = False
    mercado_account.save(update_fields=("is_active",))
    called = 0

    class SpyAdapter:
        provider = "mercado_pago"
        external = False

        def create_checkout(self, checkout_request):
            nonlocal called
            called += 1

    with pytest.raises(InvalidPayment, match="inelegível"):
        dispatch_requested_checkout(attempt=attempt, adapter=SpyAdapter(), idempotency_key=key())
    attempt.refresh_from_db()
    intent.refresh_from_db()
    assert called == 0
    assert attempt.status == PaymentAttempt.Status.FAILED
    assert attempt.dispatch_error_code == "provider_account_inactive"
    assert intent.status == PaymentIntent.Status.PENDING

    second_order = Order.objects.create(
        organization=organization,
        number=51,
        customer=payable_order.customer,
        status=Order.Status.CONFIRMED,
        currency="BRL",
        subtotal=Decimal("125.40"),
        total=Decimal("125.40"),
        customer_name_snapshot=payable_order.customer_name_snapshot,
        created_by=manager,
        confirmed_at=timezone.now(),
    )
    mercado_account.is_active = True
    mercado_account.save(update_fields=("is_active",))
    second_intent, second_attempt = create_intent_and_attempt(
        organization=organization,
        order=second_order,
        account=mercado_account,
        manager=manager,
    )

    class DisableDuringCallAdapter:
        provider = "mercado_pago"
        external = False

        def create_checkout(self, checkout_request):
            PaymentProviderAccount.objects.filter(id=mercado_account.id).update(is_active=False)
            return CheckoutResult("disabled-race", "https://checkout.example.test/disabled-race")

    result = dispatch_requested_checkout(
        attempt=second_attempt,
        adapter=DisableDuringCallAdapter(),
        idempotency_key=key(),
    )
    second_intent.refresh_from_db()
    assert result.external_resource_id == "disabled-race"
    assert second_intent.status == PaymentIntent.Status.REQUIRES_ATTENTION


@pytest.mark.django_db
def test_lease_exceeds_worker_hard_limit(organization, payable_order, mercado_account, manager, manager_membership):
    _, attempt = create_intent_and_attempt(
        organization=organization,
        order=payable_order,
        account=mercado_account,
        manager=manager,
    )
    before = timezone.now()
    claimed = claim_requested_checkout(attempt_id=attempt.id)
    assert DISPATCH_LEASE_SECONDS > settings.CELERY_TASK_TIME_LIMIT
    assert claimed.dispatch_lease_expires_at >= before + timedelta(seconds=settings.CELERY_TASK_TIME_LIMIT)


@pytest.mark.django_db
def test_dispatch_batch_continues_after_unexpected_provider_failure(
    organization, payable_order, mercado_account, manager, manager_membership
):
    _, first = create_intent_and_attempt(
        organization=organization,
        order=payable_order,
        account=mercado_account,
        manager=manager,
    )
    second_order = Order.objects.create(
        organization=organization,
        number=52,
        customer=payable_order.customer,
        status=Order.Status.CONFIRMED,
        currency="BRL",
        subtotal=Decimal("80.00"),
        total=Decimal("80.00"),
        customer_name_snapshot=payable_order.customer_name_snapshot,
        created_by=manager,
        confirmed_at=timezone.now(),
    )
    _, second = create_intent_and_attempt(
        organization=organization,
        order=second_order,
        account=mercado_account,
        manager=manager,
    )

    class Adapter:
        provider = "mercado_pago"
        external = False

        def __init__(self, should_fail):
            self.should_fail = should_fail

        def create_checkout(self, checkout_request):
            if self.should_fail:
                raise RuntimeError("controlled test failure")
            return CheckoutResult("second-resource", "https://checkout.example.test/second")

    processed = dispatch_checkout_events(adapter_resolver=lambda current: Adapter(current.id == first.id))
    first.refresh_from_db()
    second.refresh_from_db()
    assert processed == 1
    assert first.dispatch_error_code == "provider_error"
    assert first.dispatch_available_at is not None
    assert second.status == PaymentAttempt.Status.ACTIVE


@pytest.mark.django_db
def test_reconciliation_authorizes_and_scopes_before_provider_io(
    organization,
    other_organization,
    payable_order,
    mercado_account,
    manager,
    manager_membership,
    user,
    operator_membership,
):
    intent, attempt = create_intent_and_attempt(
        organization=organization,
        order=payable_order,
        account=mercado_account,
        manager=manager,
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("auth-resource", "https://checkout.example.test/auth"),
        idempotency_key=key(),
    )
    calls = 0

    class SpyAdapter:
        provider = "mercado_pago"
        external = False

        def fetch_resource(self, external_resource_id):
            nonlocal calls
            calls += 1
            return ProviderResource(external_resource_id, "pending", 12540, "BRL")

    with pytest.raises(PaymentPermissionDenied):
        fetch_and_reconcile(
            organization=organization,
            intent=intent,
            actor=user,
            expected_version=3,
            idempotency_key=key(),
            adapter=SpyAdapter(),
        )
    Membership.objects.create(
        organization=other_organization,
        user=manager,
        role=Membership.Role.MANAGER,
    )
    with pytest.raises(OrganizationMismatch):
        fetch_and_reconcile(
            organization=other_organization,
            intent=intent,
            actor=manager,
            expected_version=3,
            idempotency_key=key(),
            adapter=SpyAdapter(),
        )
    manager_membership.is_active = False
    manager_membership.save(update_fields=("is_active",))
    with pytest.raises(PaymentPermissionDenied):
        fetch_and_reconcile(
            organization=organization,
            intent=intent,
            actor=manager,
            expected_version=3,
            idempotency_key=key(),
            adapter=SpyAdapter(),
        )
    assert calls == 0


@pytest.mark.django_db
def test_cancel_verified_then_explicitly_reopen_and_switch_provider(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent, attempt = create_intent_and_attempt(
        organization=organization,
        order=payable_order,
        account=mercado_account,
        manager=manager,
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("cancel-resource", "https://checkout.example.test/cancel"),
        idempotency_key=key(),
    )
    intent.refresh_from_db()
    request_hosted_checkout_cancellation(
        organization=organization,
        intent=intent,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=key(),
    )

    class CancellationAdapter:
        provider = "mercado_pago"
        external = False

        def cancel_checkout(self, external_resource_id, *, idempotency_key):
            return ProviderResource(external_resource_id, "cancelled", 12540, "BRL")

    assert dispatch_checkout_cancellation_events(adapter_resolver=lambda current: CancellationAdapter()) == 1
    intent.refresh_from_db()
    attempt.refresh_from_db()
    assert intent.status == PaymentIntent.Status.CANCELLED
    assert attempt.status == PaymentAttempt.Status.CANCELLED

    reopened = reopen_payment_after_verified_closure(
        organization=organization,
        intent=intent,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=key(),
    )
    pagarme = PaymentProviderAccount.objects.create(
        organization=organization,
        provider=PaymentProviderAccount.Provider.PAGARME,
        display_name="Pagar.me alternativo",
        credential_alias="pagarme-switch-test",
        is_active=True,
    )
    switched = request_hosted_checkout(
        organization=organization,
        intent=reopened,
        provider_account=pagarme,
        actor=manager,
        expected_version=reopened.version,
        idempotency_key=key(),
    )
    assert switched.provider == PaymentProviderAccount.Provider.PAGARME
    assert attempt.status == PaymentAttempt.Status.CANCELLED


@pytest.mark.django_db
def test_worker_rejects_forged_cross_tenant_event_before_adapter(
    organization,
    other_organization,
    payable_order,
    mercado_account,
    manager,
    manager_membership,
):
    intent, attempt = create_intent_and_attempt(
        organization=organization,
        order=payable_order,
        account=mercado_account,
        manager=manager,
    )
    OutboxEvent.objects.filter(event_type="payment.checkout_requested", aggregate_id=intent.id).update(
        event_type="test.original_event_hidden"
    )
    enqueue_event(
        organization=other_organization,
        event_type="payment.checkout_requested",
        aggregate_type="payment_intent",
        aggregate_id=intent.id,
        payload={"payment_intent_id": str(intent.id)},
        idempotency_key=f"forged-{intent.id}",
    )
    calls = 0

    def resolver(current):
        nonlocal calls
        calls += 1

    assert dispatch_checkout_events(adapter_resolver=resolver) == 0
    attempt.refresh_from_db()
    assert calls == 0
    assert attempt.status == PaymentAttempt.Status.REQUESTED


@pytest.mark.django_db
def test_payment_admin_queryset_uses_active_organization(
    organization, other_organization, mercado_account, manager, manager_membership
):
    Membership.objects.create(
        organization=other_organization,
        user=manager,
        role=Membership.Role.MANAGER,
    )
    other_account = PaymentProviderAccount.objects.create(
        organization=other_organization,
        provider=PaymentProviderAccount.Provider.MERCADO_PAGO,
        display_name="Conta isolada",
        credential_alias="other-admin-test",
    )
    request = SimpleNamespace(
        user=manager,
        session={ACTIVE_ORGANIZATION_SESSION_KEY: str(organization.id)},
    )
    queryset = admin.site._registry[PaymentProviderAccount].get_queryset(request)
    assert list(queryset) == [mercado_account]
    assert other_account not in queryset


def test_provider_dns_is_executably_blocked():
    with pytest.raises(AssertionError, match="forbidden"):
        socket.getaddrinfo("api.mercadopago.com", 443)
