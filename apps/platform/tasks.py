from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from apps.platform.publishers import DummyOutboxPublisher, publish_event
from apps.platform.services import mark_attempt, mark_failure, mark_success, pending_events

BEAT_HEARTBEAT_KEY = "vidalys_flow:celery_beat:heartbeat"


@shared_task(name="apps.platform.tasks.record_beat_heartbeat")
def record_beat_heartbeat():
    timestamp = timezone.now().isoformat()
    cache.set(BEAT_HEARTBEAT_KEY, timestamp, timeout=90)
    return timestamp


@shared_task(name="apps.platform.tasks.publish_pending_outbox")
def publish_pending_outbox(limit=20):
    publisher = DummyOutboxPublisher()
    processed = 0
    event_ids = list(pending_events(limit=limit).values_list("id", flat=True))
    for event_id in event_ids:
        event = mark_attempt(event_id=event_id)
        if event is None:
            continue
        try:
            result = publish_event(event=event, publisher=publisher)
            if not result.accepted:
                raise RuntimeError("O publisher interno recusou o evento.")
        except Exception as exc:  # noqa: BLE001
            mark_failure(event_id=event_id, error=exc)
        else:
            mark_success(event_id=event_id)
            processed += 1
    return processed
