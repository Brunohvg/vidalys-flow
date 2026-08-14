import threading

import pytest
from django.db import close_old_connections, connections

from apps.customers.models import ContactPoint
from apps.messaging import services
from apps.messaging.exceptions import IdempotencyConflict, InvalidMessage
from apps.messaging.models import Message, MessageDeliveryAttempt, MessageTemplate, MessagingChannel
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
