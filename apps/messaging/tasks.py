from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.messaging.contextual import PURPOSE_PIX_INSTRUCTION, dispatch_pix_message
from apps.messaging.events import ALLOWLISTED_SOURCE_EVENTS, MESSAGE_CREATED
from apps.messaging.exceptions import MessagingDomainError
from apps.messaging.idempotency import claim_command, complete_command
from apps.messaging.models import Message, MessageCommandReceipt, MessageDeliveryAttempt
from apps.messaging.providers import adapter_for
from apps.messaging.services import consume_source_event, dispatch_message
from apps.platform.models import OutboxEvent


def _disabled_adapter_for(attempt):
    return adapter_for(attempt.channel.connection.provider)


@transaction.atomic
def _record_source_consumed(*, event, rejected=False):
    operation = "consume_source_event_rejected" if rejected else "consume_source_event"
    receipt, is_new = claim_command(
        organization=event.organization,
        operation=operation,
        idempotency_key=str(event.id),
        payload={"event_id": str(event.id), "event_type": event.event_type},
        source_event_id=event.id,
    )
    if is_new:
        complete_command(receipt=receipt)


def consume_source_events(*, limit=100):
    consumed_ids = MessageCommandReceipt.objects.filter(
        operation__in=("consume_source_event", "consume_source_event_rejected"),
        completed=True,
        source_event_id__isnull=False,
    ).values_list("source_event_id", flat=True)
    events = list(
        OutboxEvent.objects.filter(event_type__in=ALLOWLISTED_SOURCE_EVENTS)
        .exclude(id__in=consumed_ids)
        .select_related("organization")
        .order_by("created_at")[:limit]
    )
    processed = 0
    for event in events:
        try:
            processed += consume_source_event(event=event)
        except MessagingDomainError:
            _record_source_consumed(event=event, rejected=True)
            continue
        except Exception:
            # Infrastructure and unexpected failures remain eligible for the
            # next poll. They must never be converted into permanent domain
            # rejection by a transient database/lock/runtime condition.
            continue
        _record_source_consumed(event=event)
    return processed


@shared_task(name="apps.messaging.tasks.consume_source_events")
def consume_source_events_task(limit=100):
    return consume_source_events(limit=limit)


def dispatch_message_events(*, limit=20, adapter_resolver=None):
    resolver = adapter_resolver or _disabled_adapter_for
    pending_ids = [
        str(message_id)
        for message_id in Message.objects.filter(status=Message.Status.PENDING).values_list("id", flat=True)
    ]
    events = OutboxEvent.objects.filter(event_type=MESSAGE_CREATED, aggregate_id__in=pending_ids).order_by(
        "created_at"
    )[:limit]
    processed = 0
    for event in events:
        attempt = (
            MessageDeliveryAttempt.objects.select_related("message", "channel", "channel__connection")
            .filter(
                organization=event.organization,
                message_id=event.aggregate_id,
                status=MessageDeliveryAttempt.Status.REQUESTED,
            )
            .order_by("created_at")
            .first()
        )
        if attempt is None:
            continue
        if attempt.dispatch_available_at and attempt.dispatch_available_at > timezone.now():
            continue
        try:
            dispatcher = dispatch_pix_message if attempt.message.purpose == PURPOSE_PIX_INSTRUCTION else dispatch_message
            dispatcher(attempt=attempt, adapter=resolver(attempt), idempotency_key=str(event.id))
        except Exception:
            continue
        processed += 1
    return processed


@shared_task(name="apps.messaging.tasks.dispatch_messages")
def dispatch_messages(limit=20):
    return dispatch_message_events(limit=limit)
