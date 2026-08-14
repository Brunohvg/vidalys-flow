import threading
from datetime import timedelta

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone

from apps.customers.models import ContactPoint, Customer
from apps.messaging import services
from apps.messaging.exceptions import IdempotencyConflict, InvalidMessage, VersionConflict
from apps.messaging.models import (
    Message,
    MessageAutomationRule,
    MessageDeliveryAttempt,
    MessageTemplate,
    MessagingChannel,
    MessagingPreference,
)
from apps.messaging.providers import SendResult
from apps.messaging.tests.conftest import key
from apps.organizations.models import Organization
from apps.users.models import User


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_manual_command_creates_one_message(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    command_key = key()
    barrier = threading.Barrier(2)
    ids = []
    expected_errors = []
    unexpected_errors = []

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            message = services.create_message_from_command(
                organization=Organization.objects.get(id=organization.id),
                actor=User.objects.get(id=manager.id),
                source_type=Message.SourceType.ORDER,
                source_id=messaging_order.id,
                purpose="order_confirmation",
                template=MessageTemplate.objects.get(id=whatsapp_template.id),
                channel=MessagingChannel.objects.get(id=whatsapp_channel.id),
                contact_point=ContactPoint.objects.get(id=messaging_customer[1].id),
                idempotency_key=command_key,
            )
            ids.append(message.id)
        except IdempotencyConflict as exc:
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
    assert len(ids) + len(expected_errors) == 2
    assert Message.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_dispatchers_call_provider_once(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=messaging_customer[1],
        idempotency_key=key(),
    )
    barrier = threading.Barrier(2)
    calls = []
    outcomes = []
    call_lock = threading.Lock()

    class Adapter:
        provider = "evolution"
        external = False

        def send_text(self, request):
            with call_lock:
                calls.append(request.provider_correlation_tag)
            return SendResult("concurrent-message-id", True)

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            result = services.dispatch_message(
                attempt=MessageDeliveryAttempt.objects.get(message_id=message.id),
                adapter=Adapter(),
                idempotency_key=key(),
            )
            outcomes.append(result.status)
        except InvalidMessage:
            outcomes.append("rejected")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(outcomes) == ["rejected", "sent"]
    assert len(calls) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("concurrent_change", ["suppression", "contact", "customer_merge", "channel", "source"])
def test_dispatch_revalidates_changes_at_send_authorization_boundary(
    concurrent_change,
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    monkeypatch,
):
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=messaging_customer[1],
        idempotency_key=key(),
    )
    ready = threading.Event()
    proceed = threading.Event()
    provider_calls = []
    original_prepare = services.prepare_send_request

    def delayed_prepare(**kwargs):
        ready.set()
        assert proceed.wait(timeout=5)
        return original_prepare(**kwargs)

    monkeypatch.setattr(services, "prepare_send_request", delayed_prepare)

    class Adapter:
        provider = "evolution"
        external = False

        def send_text(self, request):
            provider_calls.append(request.destination)
            return SendResult("must-not-send", True)

    outcomes = []

    def worker():
        close_old_connections()
        try:
            result = services.dispatch_message(
                attempt=MessageDeliveryAttempt.objects.get(message_id=message.id),
                adapter=Adapter(),
                idempotency_key=key(),
            )
            outcomes.append(result.status)
        finally:
            connections.close_all()

    thread = threading.Thread(target=worker)
    thread.start()
    assert ready.wait(timeout=5)
    if concurrent_change == "suppression":
        MessagingPreference.objects.filter(id=allowed_preference.id).update(is_active=False)
        MessagingPreference.objects.create(
            organization=organization,
            contact_point=messaging_customer[1],
            channel="whatsapp",
            purpose="order_confirmation",
            decision="suppressed",
            provenance="concurrent_opt_out",
            effective_at=allowed_preference.effective_at,
        )
    elif concurrent_change == "contact":
        contact = messaging_customer[1]
        contact.normalized_value = "+5511888887777"
        contact.save(update_fields=("normalized_value",))
    elif concurrent_change == "customer_merge":
        customer = messaging_customer[0]
        customer.merged_into = Customer.objects.create(
            organization=organization,
            customer_type=Customer.Type.INDIVIDUAL,
            display_name="Customer canônico",
        )
        customer.save(update_fields=("merged_into",))
    elif concurrent_change == "channel":
        whatsapp_channel.state = MessagingChannel.State.DISABLED
        whatsapp_channel.save(update_fields=("state",))
    else:
        messaging_order.version += 1
        messaging_order.save(update_fields=("version",))
    proceed.set()
    thread.join(timeout=10)

    assert outcomes == [Message.Status.FAILED]
    assert provider_calls == []


@pytest.mark.django_db(transaction=True)
def test_concurrent_rule_updates_allow_only_one_expected_version(
    organization,
    manager,
    manager_membership,
    whatsapp_template,
    whatsapp_channel,
):
    rule = MessageAutomationRule.objects.create(
        organization=organization,
        event_type="order.confirmed",
        template=whatsapp_template,
        channel=whatsapp_channel,
        purpose="order_confirmation",
        is_enabled=False,
    )
    barrier = threading.Barrier(2)
    versions = []
    conflicts = []
    unexpected = []

    def worker(enabled):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            updated = services.upsert_automation_rule(
                organization=Organization.objects.get(id=organization.id),
                actor=User.objects.get(id=manager.id),
                event_type="order.confirmed",
                template=MessageTemplate.objects.get(id=whatsapp_template.id),
                channel=MessagingChannel.objects.get(id=whatsapp_channel.id),
                purpose="order_confirmation",
                is_enabled=enabled,
                expected_version=rule.version,
                idempotency_key=key(),
            )
            versions.append(updated.version)
        except VersionConflict as exc:
            conflicts.append(exc)
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(enabled,)) for enabled in (True, False)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not unexpected
    assert versions == [2]
    assert len(conflicts) == 1
    rule.refresh_from_db()
    assert rule.version == 2


@pytest.mark.django_db(transaction=True)
def test_dispatch_revalidates_checkout_expiry_at_send_authorization_boundary(
    organization,
    manager,
    manager_membership,
    active_checkout_intent,
    messaging_customer,
    checkout_template,
    whatsapp_channel,
    allowed_checkout_preference,
    monkeypatch,
):
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.PAYMENT,
        source_id=active_checkout_intent.id,
        purpose="checkout_link",
        template=checkout_template,
        channel=whatsapp_channel,
        contact_point=messaging_customer[1],
        idempotency_key=key(),
    )
    ready = threading.Event()
    proceed = threading.Event()
    calls = []
    original_prepare = services.prepare_send_request

    def delayed_prepare(**kwargs):
        ready.set()
        assert proceed.wait(timeout=5)
        return original_prepare(**kwargs)

    monkeypatch.setattr(services, "prepare_send_request", delayed_prepare)

    class Adapter:
        provider = "evolution"
        external = False

        def send_text(self, request):
            calls.append(request.body)
            return SendResult("must-not-send-checkout", True)

    outcomes = []

    def worker():
        close_old_connections()
        try:
            result = services.dispatch_message(
                attempt=MessageDeliveryAttempt.objects.get(message_id=message.id),
                adapter=Adapter(),
                idempotency_key=key(),
            )
            outcomes.append(result.status)
        finally:
            connections.close_all()

    thread = threading.Thread(target=worker)
    thread.start()
    assert ready.wait(timeout=5)
    checkout_attempt = active_checkout_intent.attempts.get()
    checkout_attempt.expires_at = timezone.now() - timedelta(seconds=1)
    checkout_attempt.save(update_fields=("expires_at",))
    proceed.set()
    thread.join(timeout=10)

    assert outcomes == [Message.Status.FAILED]
    assert calls == []
