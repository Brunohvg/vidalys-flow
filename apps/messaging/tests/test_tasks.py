import uuid

import pytest
from django.conf import settings
from django.db import OperationalError
from django.utils import timezone

from apps.fulfillment.models import Fulfillment
from apps.messaging.models import (
    Message,
    MessageAutomationRule,
    MessageCommandReceipt,
    MessageTemplate,
    MessagingPreference,
)
from apps.messaging.providers import SendResult
from apps.messaging.services import create_message_from_command
from apps.messaging.tasks import consume_source_events, dispatch_message_events
from apps.payments.models import PaymentIntent
from apps.platform.models import OutboxEvent
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


@pytest.mark.parametrize(
    ("event_type", "source_kind", "source_status", "semantic_key", "purpose"),
    (
        ("order.confirmed", "order", "confirmed", "order_confirmation", "order_confirmation"),
        ("fulfillment.ready", "fulfillment", Fulfillment.Status.READY, "fulfillment_ready", "fulfillment_progress"),
        (
            "fulfillment.dispatched",
            "fulfillment",
            Fulfillment.Status.IN_TRANSIT,
            "fulfillment_dispatched",
            "fulfillment_progress",
        ),
        (
            "fulfillment.completed",
            "fulfillment",
            Fulfillment.Status.COMPLETED,
            "fulfillment_completed",
            "fulfillment_progress",
        ),
        (
            "payment.checkout_activated",
            "payment",
            PaymentIntent.Status.AWAITING_PAYMENT,
            "checkout_link",
            "checkout_link",
        ),
        (
            "payment.status_changed",
            "payment",
            PaymentIntent.Status.PAID,
            "payment_paid",
            "payment_confirmation",
        ),
    ),
)
def test_each_allowlisted_source_event_creates_exactly_one_message(
    organization,
    manager,
    messaging_order,
    messaging_customer,
    whatsapp_channel,
    active_checkout_intent,
    event_type,
    source_kind,
    source_status,
    semantic_key,
    purpose,
):
    if source_kind == "order":
        source = messaging_order
        aggregate_type = "order"
        identifier_key = "order_id"
    elif source_kind == "fulfillment":
        source = Fulfillment.objects.create(
            organization=organization,
            order=messaging_order,
            sequence=1,
            method=Fulfillment.Method.DELIVERY,
            status=source_status,
            created_by=manager,
        )
        aggregate_type = "fulfillment"
        identifier_key = "fulfillment_id"
    else:
        source = active_checkout_intent
        source.status = source_status
        if source_status == PaymentIntent.Status.PAID:
            source.paid_at = timezone.now()
        source.version += 1
        source.save(update_fields=("status", "paid_at", "version", "updated_at"))
        aggregate_type = "payment_intent"
        identifier_key = "payment_intent_id"

    template_bodies = {
        "order_confirmation": (
            "Olá {customer_name}, seu pedido {order_number} foi confirmado.",
            ["customer_name", "order_number"],
        ),
        "fulfillment_ready": (
            "Olá {customer_name}, {order_number}: {fulfillment_status}.",
            ["customer_name", "order_number", "fulfillment_status"],
        ),
        "fulfillment_dispatched": (
            "Olá {customer_name}, {order_number}: {fulfillment_status}.",
            ["customer_name", "order_number", "fulfillment_status"],
        ),
        "fulfillment_completed": (
            "Olá {customer_name}, {order_number}: {fulfillment_status}.",
            ["customer_name", "order_number", "fulfillment_status"],
        ),
        "checkout_link": (
            "Olá {customer_name}, pague seu pedido {order_number} em {checkout_link}.",
            ["customer_name", "order_number", "checkout_link"],
        ),
        "payment_paid": (
            "Olá {customer_name}, {order_number}: {amount} {currency}.",
            ["customer_name", "order_number", "amount", "currency"],
        ),
    }
    body_text, schema = template_bodies[semantic_key]
    template = MessageTemplate.objects.create(
        organization=organization,
        semantic_key=semantic_key,
        name=semantic_key,
        channel=MessageTemplate.Channel.WHATSAPP,
        body_text=body_text,
        parameter_schema=schema,
    )
    MessagingPreference.objects.create(
        organization=organization,
        contact_point=messaging_customer[1],
        channel="whatsapp",
        purpose=purpose,
        decision=MessagingPreference.Decision.ALLOWED,
        provenance="consent_record",
        effective_at=timezone.now(),
    )
    MessageAutomationRule.objects.create(
        organization=organization,
        event_type=event_type,
        event_version=1,
        template=template,
        channel=whatsapp_channel,
        purpose=purpose,
        is_enabled=True,
    )
    event = enqueue_event(
        organization=organization,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=source.id,
        payload={identifier_key: str(source.id), "status": source_status, "version": source.version},
        idempotency_key=f"messaging-matrix-{uuid.uuid4()}",
        event_contract_version=1,
    )

    assert consume_source_events() == 1
    assert Message.objects.filter(source_event_id=event.id, purpose=purpose).count() == 1
    assert consume_source_events() == 0


@pytest.mark.parametrize(
    ("event_type", "source_status", "semantic_key"),
    (
        ("fulfillment.ready", Fulfillment.Status.IN_TRANSIT, "fulfillment_ready"),
        ("fulfillment.dispatched", Fulfillment.Status.READY, "fulfillment_dispatched"),
        ("fulfillment.completed", Fulfillment.Status.READY, "fulfillment_completed"),
    ),
)
def test_fulfillment_event_rejects_incompatible_current_state(
    organization,
    manager,
    messaging_order,
    messaging_customer,
    whatsapp_channel,
    event_type,
    source_status,
    semantic_key,
):
    fulfillment = Fulfillment.objects.create(
        organization=organization,
        order=messaging_order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        status=source_status,
        created_by=manager,
    )
    template = MessageTemplate.objects.create(
        organization=organization,
        semantic_key=semantic_key,
        name=semantic_key,
        channel=MessageTemplate.Channel.WHATSAPP,
        body_text="Olá {customer_name}, {order_number}: {fulfillment_status}.",
        parameter_schema=["customer_name", "order_number", "fulfillment_status"],
    )
    MessagingPreference.objects.create(
        organization=organization,
        contact_point=messaging_customer[1],
        channel="whatsapp",
        purpose="fulfillment_progress",
        decision=MessagingPreference.Decision.ALLOWED,
        provenance="consent_record",
        effective_at=timezone.now(),
    )
    MessageAutomationRule.objects.create(
        organization=organization,
        event_type=event_type,
        event_version=1,
        template=template,
        channel=whatsapp_channel,
        purpose="fulfillment_progress",
        is_enabled=True,
    )
    event = enqueue_event(
        organization=organization,
        event_type=event_type,
        aggregate_type="fulfillment",
        aggregate_id=fulfillment.id,
        payload={
            "fulfillment_id": str(fulfillment.id),
            "status": fulfillment.status,
            "version": fulfillment.version,
        },
        idempotency_key=f"messaging-state-mismatch-{uuid.uuid4()}",
    )

    assert consume_source_events() == 0
    assert not Message.objects.filter(source_event_id=event.id).exists()


def test_source_event_with_unknown_contract_version_is_rejected(
    organization,
    messaging_order,
    enabled_order_rule,
):
    event = enqueue_event(
        organization=organization,
        event_type="order.confirmed",
        aggregate_type="order",
        aggregate_id=messaging_order.id,
        payload={"order_id": str(messaging_order.id), "version": messaging_order.version},
        idempotency_key=f"messaging-contract-{uuid.uuid4()}",
        event_contract_version=999,
    )

    assert consume_source_events() == 0
    assert not Message.objects.filter(source_event_id=event.id).exists()
    assert MessageCommandReceipt.objects.filter(
        source_event_id=event.id,
        operation="consume_source_event_rejected",
        completed=True,
    ).exists()


def test_source_event_without_contract_version_is_rejected(
    organization,
    messaging_order,
    enabled_order_rule,
):
    event = OutboxEvent.objects.create(
        organization=organization,
        event_type="order.confirmed",
        aggregate_type="order",
        aggregate_id=str(messaging_order.id),
        payload={"order_id": str(messaging_order.id), "version": messaging_order.version},
        idempotency_key=f"messaging-contract-missing-{uuid.uuid4()}",
        available_at=timezone.now(),
    )

    assert consume_source_events() == 0
    assert not Message.objects.filter(source_event_id=event.id).exists()
    assert MessageCommandReceipt.objects.filter(
        source_event_id=event.id,
        operation="consume_source_event_rejected",
        completed=True,
    ).exists()


def test_rule_with_different_contract_version_cannot_consume_event(
    organization,
    messaging_order,
    enabled_order_rule,
):
    enabled_order_rule.event_version = 999
    enabled_order_rule.save(update_fields=("event_version",))
    event = enqueue_event(
        organization=organization,
        event_type="order.confirmed",
        aggregate_type="order",
        aggregate_id=messaging_order.id,
        payload={"order_id": str(messaging_order.id), "version": messaging_order.version},
        idempotency_key=f"messaging-rule-contract-{uuid.uuid4()}",
        event_contract_version=1,
    )

    assert consume_source_events() == 0
    assert not Message.objects.filter(source_event_id=event.id).exists()


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
