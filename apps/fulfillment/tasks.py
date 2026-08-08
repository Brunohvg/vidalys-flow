from celery import shared_task

from apps.fulfillment.models import FulfillmentCommandReceipt
from apps.fulfillment.services import consume_order_cancelled_event
from apps.platform.models import OutboxEvent


@shared_task(name="apps.fulfillment.tasks.consume_order_cancellations")
def consume_order_cancellations(limit=100):
    consumed_ids = FulfillmentCommandReceipt.objects.filter(
        operation="consume_order_cancelled_event",
        completed=True,
        source_event_id__isnull=False,
    ).values_list("source_event_id", flat=True)
    events = list(
        OutboxEvent.objects.filter(event_type="order.cancelled")
        .exclude(id__in=consumed_ids)
        .select_related("organization")
        .order_by("created_at")[:limit]
    )
    cancelled = 0
    for event in events:
        cancelled += consume_order_cancelled_event(event=event)
    return cancelled
