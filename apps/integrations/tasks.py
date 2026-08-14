from celery import shared_task
from django.utils import timezone

from .models import IntegrationDelivery
from .services import dispatch_delivery, reconcile_delivery


@shared_task
def dispatch_pending_deliveries(limit=50):
    ids = list(IntegrationDelivery.objects.filter(status__in=("queued", "failed"), next_attempt_at__lte=timezone.now()).values_list("id", flat=True)[:limit])
    ids += list(IntegrationDelivery.objects.filter(status="queued", next_attempt_at__isnull=True).exclude(id__in=ids).values_list("id", flat=True)[: max(0, limit - len(ids))])
    for delivery_id in ids:
        dispatch_delivery(delivery_id)
    return len(ids)


@shared_task
def reconcile_uncertain_deliveries(limit=50):
    deliveries = list(IntegrationDelivery.objects.filter(status="uncertain").select_related("connection")[:limit])
    for delivery in deliveries:
        reconcile_delivery(delivery)
    return len(deliveries)
