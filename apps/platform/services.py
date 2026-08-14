from django.db import transaction
from django.utils import timezone

from apps.audit.services import sanitize_payload
from apps.platform.models import OutboxEvent

MAX_ATTEMPTS = 5


def enqueue_event(
    *,
    organization,
    event_type,
    aggregate_type,
    aggregate_id,
    payload,
    idempotency_key,
    available_at=None,
    event_contract_version=1,
):
    if isinstance(event_contract_version, bool) or not isinstance(event_contract_version, int):
        raise ValueError("event_contract_version deve ser um inteiro positivo.")
    if event_contract_version < 1:
        raise ValueError("event_contract_version deve ser um inteiro positivo.")
    versioned_payload = {**payload, "event_contract_version": event_contract_version}
    event, _ = OutboxEvent.objects.get_or_create(
        organization=organization,
        idempotency_key=idempotency_key,
        defaults={
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "payload": sanitize_payload(versioned_payload),
            "available_at": available_at or timezone.now(),
        },
    )
    return event


def pending_events(*, limit=100):
    return OutboxEvent.objects.filter(
        status__in=(OutboxEvent.Status.PENDING, OutboxEvent.Status.RETRY),
        available_at__lte=timezone.now(),
    ).order_by("available_at", "created_at")[:limit]


@transaction.atomic
def mark_attempt(*, event_id):
    event = OutboxEvent.objects.select_for_update().get(pk=event_id)
    if event.status not in (OutboxEvent.Status.PENDING, OutboxEvent.Status.RETRY):
        return None
    event.attempts += 1
    event.status = OutboxEvent.Status.PROCESSING
    event.last_error = ""
    event.save(update_fields=("attempts", "status", "last_error", "updated_at"))
    return event


@transaction.atomic
def mark_success(*, event_id):
    event = OutboxEvent.objects.select_for_update().get(pk=event_id)
    event.status = OutboxEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.last_error = ""
    event.save(update_fields=("status", "processed_at", "last_error", "updated_at"))
    return event


@transaction.atomic
def mark_failure(*, event_id, error):
    event = OutboxEvent.objects.select_for_update().get(pk=event_id)
    event.status = OutboxEvent.Status.DEAD if event.attempts >= MAX_ATTEMPTS else OutboxEvent.Status.RETRY
    event.last_error = error.__class__.__name__[:500]
    event.available_at = timezone.now()
    event.save(update_fields=("status", "last_error", "available_at", "updated_at"))
    return event
