from celery import shared_task

from apps.payments.models import PaymentCommandReceipt, PaymentIntent
from apps.payments.services import consume_order_cancelled
from apps.platform.models import OutboxEvent


@shared_task(name="apps.payments.tasks.consume_order_cancellations")
def consume_order_cancellations(limit=20):
    consumed_ids = PaymentCommandReceipt.objects.filter(
        operation="payment_consume_order_cancelled",
        completed=True,
        source_event_id__isnull=False,
    ).values_list("source_event_id", flat=True)
    events = list(
        OutboxEvent.objects.filter(event_type="order.cancelled")
        .exclude(id__in=consumed_ids)
        .select_related("organization")
        .order_by("created_at")[:limit]
    )
    processed = 0
    for event in events:
        order_id = event.payload.get("order_id")
        if not PaymentIntent.objects.filter(organization=event.organization, order_id=order_id).exists():
            continue
        consume_order_cancelled(
            organization=event.organization,
            order_id=order_id,
            source_event_id=event.id,
        )
        processed += 1
    return processed

