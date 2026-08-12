from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.payments.models import PaymentAttempt, PaymentCommandReceipt, PaymentIntent
from apps.payments.providers import MercadoPagoCheckoutProAdapter, PagarmePaymentLinkAdapter
from apps.payments.services import (
    complete_cancellation_event_for_terminal_attempt,
    consume_order_cancelled,
    dispatch_checkout_cancellation,
    dispatch_requested_checkout,
)
from apps.platform.models import OutboxEvent
from apps.platform.services import mark_success


def _disabled_adapter_for(attempt):
    adapters = {
        "mercado_pago": MercadoPagoCheckoutProAdapter,
        "pagarme": PagarmePaymentLinkAdapter,
    }
    return adapters[attempt.provider]()


def dispatch_checkout_events(*, limit=20, adapter_resolver=None):
    resolver = adapter_resolver or _disabled_adapter_for
    requested_intent_ids = [
        str(intent_id)
        for intent_id in PaymentAttempt.objects.filter(status=PaymentAttempt.Status.REQUESTED)
        .filter(Q(dispatch_available_at__isnull=True) | Q(dispatch_available_at__lte=timezone.now()))
        .values_list("intent_id", flat=True)
    ]
    events = OutboxEvent.objects.filter(
        event_type="payment.checkout_requested",
        aggregate_id__in=requested_intent_ids,
    ).order_by("created_at")[:limit]
    processed = 0
    for event in events:
        attempt = (
            PaymentAttempt.objects.filter(
                organization=event.organization,
                intent_id=event.aggregate_id,
                status=PaymentAttempt.Status.REQUESTED,
            )
            .order_by("created_at")
            .first()
        )
        if attempt is None:
            continue
        try:
            dispatch_requested_checkout(
                attempt=attempt,
                adapter=resolver(attempt),
                idempotency_key=str(event.id),
            )
        except Exception:
            continue
        processed += 1
    return processed


@shared_task(name="apps.payments.tasks.dispatch_checkout_requests")
def dispatch_checkout_requests(limit=20):
    return dispatch_checkout_events(limit=limit)


def dispatch_checkout_cancellation_events(*, limit=20, adapter_resolver=None):
    resolver = adapter_resolver or _disabled_adapter_for
    correlated_attempt_ids = [
        str(attempt_id)
        for attempt_id in PaymentAttempt.objects.filter(
            cancellation_event_id__isnull=False,
            cancellation_completed_at__isnull=True,
        ).values_list("id", flat=True)
    ]
    events = OutboxEvent.objects.filter(
        event_type="payment.checkout_cancellation_requested",
        aggregate_type="payment_attempt",
        aggregate_id__in=correlated_attempt_ids,
    ).order_by("created_at")[:limit]
    processed = 0
    for event in events:
        attempt = (
            PaymentAttempt.objects.filter(
                organization=event.organization,
                id=event.aggregate_id,
                cancellation_event_id=event.id,
                cancellation_completed_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )
        if attempt is None:
            continue
        if complete_cancellation_event_for_terminal_attempt(attempt_id=attempt.id, event_id=event.id):
            mark_success(event_id=event.id)
            processed += 1
            continue
        if attempt.status not in {PaymentAttempt.Status.ACTIVE, PaymentAttempt.Status.PROCESSING}:
            continue
        if attempt.dispatch_available_at and attempt.dispatch_available_at > timezone.now():
            continue
        try:
            _, cancellation_complete = dispatch_checkout_cancellation(
                attempt=attempt,
                adapter=resolver(attempt),
                idempotency_key=str(event.id),
            )
        except Exception:
            continue
        if not cancellation_complete:
            continue
        mark_success(event_id=event.id)
        processed += 1
    return processed


@shared_task(name="apps.payments.tasks.dispatch_checkout_cancellations")
def dispatch_checkout_cancellations(limit=20):
    return dispatch_checkout_cancellation_events(limit=limit)


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
