import pytest
from django.utils import timezone

from apps.organizations.models import Organization
from apps.platform.guardrails import ExternalEffectBlockedError
from apps.platform.models import OutboxEvent
from apps.platform.publishers import PublishResult, publish_event
from apps.platform.services import enqueue_event, mark_attempt, mark_failure, mark_success, pending_events
from apps.platform.tasks import publish_pending_outbox


@pytest.fixture
def organization():
    return Organization.objects.create(name="Org", slug="org")


@pytest.mark.django_db
def test_enqueue_is_idempotent(organization):
    first = enqueue_event(
        organization=organization,
        event_type="organization.created",
        aggregate_type="organization",
        aggregate_id=organization.id,
        payload={"id": str(organization.id)},
        idempotency_key="organization-created",
    )
    second = enqueue_event(
        organization=organization,
        event_type="organization.created",
        aggregate_type="organization",
        aggregate_id=organization.id,
        payload={"id": "ignored-duplicate"},
        idempotency_key="organization-created",
    )
    assert first == second
    assert OutboxEvent.objects.count() == 1
    assert first.payload["event_contract_version"] == 1


@pytest.mark.parametrize("event_contract_version", (True, 0, "1"))
@pytest.mark.django_db
def test_enqueue_rejects_invalid_event_contract_version(organization, event_contract_version):
    with pytest.raises(ValueError, match="inteiro positivo"):
        enqueue_event(
            organization=organization,
            event_type="organization.created",
            aggregate_type="organization",
            aggregate_id=organization.id,
            payload={"id": str(organization.id)},
            idempotency_key=f"invalid-contract-{event_contract_version}",
            event_contract_version=event_contract_version,
        )


@pytest.mark.django_db
def test_pending_selection_and_state_transitions(organization):
    event = enqueue_event(
        organization=organization,
        event_type="test",
        aggregate_type="test",
        aggregate_id="1",
        payload={},
        idempotency_key="test-1",
    )
    assert list(pending_events()) == [event]
    attempted = mark_attempt(event_id=event.id)
    assert attempted.attempts == 1
    assert attempted.status == OutboxEvent.Status.PROCESSING
    succeeded = mark_success(event_id=event.id)
    assert succeeded.status == OutboxEvent.Status.PROCESSED
    assert succeeded.processed_at is not None


@pytest.mark.django_db
def test_failure_is_retryable_and_error_is_sanitized(organization):
    event = OutboxEvent.objects.create(
        organization=organization,
        event_type="test",
        aggregate_type="test",
        aggregate_id="1",
        payload={},
        idempotency_key="test-failure",
        available_at=timezone.now(),
    )
    mark_attempt(event_id=event.id)
    failed = mark_failure(event_id=event.id, error=RuntimeError("sensitive provider response"))
    assert failed.status == OutboxEvent.Status.RETRY
    assert failed.last_error == "RuntimeError"


@pytest.mark.django_db
def test_dummy_publisher_processes_without_external_io(organization):
    enqueue_event(
        organization=organization,
        event_type="test",
        aggregate_type="test",
        aggregate_id="1",
        payload={},
        idempotency_key="dummy",
    )
    assert publish_pending_outbox() == 1
    assert OutboxEvent.objects.get().status == OutboxEvent.Status.PROCESSED


@pytest.mark.django_db
def test_demo_mode_blocks_external_publisher(settings, organization):
    settings.VIDALYS_DEMO_MODE = True
    event = enqueue_event(
        organization=organization,
        event_type="test",
        aggregate_type="test",
        aggregate_id="1",
        payload={},
        idempotency_key="external",
    )

    class ExternalPublisher:
        external = True

        def publish(self, event):
            return PublishResult(accepted=True)

    with pytest.raises(ExternalEffectBlockedError):
        publish_event(event=event, publisher=ExternalPublisher())
