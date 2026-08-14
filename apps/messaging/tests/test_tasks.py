import uuid

import pytest
from django.conf import settings
from django.db import OperationalError

from apps.messaging.models import Message, MessageCommandReceipt
from apps.messaging.providers import SendResult
from apps.messaging.services import create_message_from_command
from apps.messaging.tasks import consume_source_events, dispatch_message_events
from apps.platform.services import enqueue_event
from config.celery import app as celery_app

pytestmark = pytest.mark.django_db


def test_messaging_tasks_are_registered_by_celery():
    celery_app.loader.import_default_modules()
    assert {
        "apps.messaging.tasks.consume_source_events",
        "apps.messaging.tasks.dispatch_messages",
    } <= set(celery_app.tasks)


def test_messaging_task_routes_and_queues():
    queues = {queue.name: queue for queue in settings.CELERY_TASK_QUEUES}
    assert settings.CELERY_TASK_ROUTES["apps.messaging.tasks.consume_source_events"] == {"queue": "default"}
    assert settings.CELERY_TASK_ROUTES["apps.messaging.tasks.dispatch_messages"] == {"queue": "integrations"}
    assert queues["integrations"].routing_key == "integrations"
    assert queues["default"].exchange.name == queues["integrations"].exchange.name == "vidalys"


def test_consume_source_events_creates_message_and_is_idempotent(
    organization,
    manager,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    enabled_order_rule,
):
    event = enqueue_event(
        organization=organization,
        event_type="order.confirmed",
        aggregate_type="order",
        aggregate_id=messaging_order.id,
        payload={"order_id": str(messaging_order.id), "status": "confirmed", "version": messaging_order.version},
        idempotency_key=f"messaging-task-{uuid.uuid4()}",
    )
    assert consume_source_events() == 1
    assert Message.objects.filter(source_event_id=event.id).count() == 1
    assert consume_source_events() == 0


def test_consume_source_events_ignores_unknown_event(organization):
    enqueue_event(
        organization=organization,
        event_type="order.cancelled",
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"order_id": "missing"},
        idempotency_key=f"messaging-unknown-{uuid.uuid4()}",
    )
    assert consume_source_events() == 0


def test_disabled_rule_does_not_create_message(
    organization,
    manager,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    enabled_order_rule,
):
    enabled_order_rule.is_enabled = False
    enabled_order_rule.save(update_fields=("is_enabled",))
    enqueue_event(
        organization=organization,
        event_type="order.confirmed",
        aggregate_type="order",
        aggregate_id=messaging_order.id,
        payload={"order_id": str(messaging_order.id), "status": "confirmed", "version": messaging_order.version},
        idempotency_key=f"messaging-disabled-{uuid.uuid4()}",
    )
    assert consume_source_events() == 0


def test_transient_source_consumer_failure_remains_retryable(
    organization,
    manager,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    enabled_order_rule,
    monkeypatch,
):
    event = enqueue_event(
        organization=organization,
        event_type="order.confirmed",
        aggregate_type="order",
        aggregate_id=messaging_order.id,
        payload={"order_id": str(messaging_order.id), "status": "confirmed", "version": messaging_order.version},
        idempotency_key=f"messaging-transient-{uuid.uuid4()}",
    )
    original = consume_source_events.__globals__["consume_source_event"]

    def transient_failure(*, event):
        raise OperationalError("temporary database outage")

    monkeypatch.setitem(consume_source_events.__globals__, "consume_source_event", transient_failure)
    assert consume_source_events() == 0
    assert not MessageCommandReceipt.objects.filter(source_event_id=event.id).exists()

    monkeypatch.setitem(consume_source_events.__globals__, "consume_source_event", original)
    assert consume_source_events() == 1
    assert Message.objects.filter(source_event_id=event.id).count() == 1


def test_dispatch_message_events_dispatches_pending_message(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    message = create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=str(uuid.uuid4()),
    )

    class FakeResolver:
        def __call__(self, attempt):
            class FakeAdapter:
                provider = "evolution"
                external = False

                def send_text(self, request):
                    return SendResult("worker-message-id", True)

            return FakeAdapter()

    assert dispatch_message_events(adapter_resolver=FakeResolver()) == 1
    message.refresh_from_db()
    assert message.status == Message.Status.SENT
    assert dispatch_message_events(adapter_resolver=FakeResolver()) == 0
