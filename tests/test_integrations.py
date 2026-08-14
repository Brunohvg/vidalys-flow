import pytest

from apps.integrations.adapters import ReferenceAdapter
from apps.integrations.exceptions import (
    IntegrationAmbiguousError,
    IntegrationContractError,
    IntegrationPermanentError,
    IntegrationTransientError,
)
from apps.integrations.models import IntegrationConnection, IntegrationDelivery, IntegrationEndpoint
from apps.integrations.services import create_delivery, dispatch_delivery, ingest_webhook, reconcile_delivery
from apps.organizations.models import Organization
from apps.platform.models import OutboxEvent

pytestmark = pytest.mark.django_db


def setup_integration():
    org = Organization.objects.create(name="Org", slug="org-integrations")
    connection = IntegrationConnection.objects.create(
        organization=org,
        key="reference",
        status="active",
    )
    egress = IntegrationEndpoint.objects.create(
        organization=org,
        connection=connection,
        key="orders-out",
        direction="egress",
        contract_version=1,
        is_active=True,
    )
    ingress = IntegrationEndpoint.objects.create(
        organization=org,
        connection=connection,
        key="events-in",
        direction="ingress",
        contract_version=1,
        is_active=True,
    )
    return org, connection, egress, ingress


def test_reference_adapter_is_offline_and_deterministic():
    adapter = ReferenceAdapter()
    assert adapter.send(payload={}, idempotency_key="abc").external_id == "ref-abc"
    with pytest.raises(IntegrationTransientError):
        adapter.send(payload={"scenario": "transient_failure"}, idempotency_key="a")
    with pytest.raises(IntegrationPermanentError):
        adapter.send(payload={"scenario": "permanent_failure"}, idempotency_key="a")
    with pytest.raises(IntegrationAmbiguousError):
        adapter.send(payload={"scenario": "timeout"}, idempotency_key="a")


def test_delivery_success_minimization_and_transactional_outbox():
    org, _, endpoint, _ = setup_integration()
    delivery = create_delivery(
        organization=org,
        endpoint=endpoint,
        source_type="order",
        source_id="1",
        source_version=1,
        operation_key="export",
        idempotency_key="idem-1",
        payload={"state": "confirmed"},
    )
    event = OutboxEvent.objects.get(
        organization=org,
        idempotency_key=f"integration-delivery:{delivery.id}:queued",
    )
    assert event.payload["delivery_id"] == str(delivery.id)
    dispatch_delivery(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == IntegrationDelivery.Status.SUCCEEDED
    assert delivery.attempts.get().external_id.startswith("ref-")


def test_payload_key_allowlist_rejects_arbitrary_or_nested_data():
    org, _, endpoint, _ = setup_integration()
    with pytest.raises(IntegrationContractError):
        create_delivery(
            organization=org,
            endpoint=endpoint,
            source_type="order",
            source_id="x",
            source_version=1,
            operation_key="export",
            idempotency_key="bad-1",
            payload={"customer_email": "x@example.com"},
        )
    with pytest.raises(IntegrationContractError):
        create_delivery(
            organization=org,
            endpoint=endpoint,
            source_type="order",
            source_id="x",
            source_version=1,
            operation_key="export",
            idempotency_key="bad-2",
            payload={"state": {"nested": "no"}},
        )


def test_ambiguous_acceptance_never_blind_retries():
    org, _, endpoint, _ = setup_integration()
    delivery = create_delivery(
        organization=org,
        endpoint=endpoint,
        source_type="order",
        source_id="2",
        source_version=1,
        operation_key="export",
        idempotency_key="idem-2",
        payload={"scenario": "timeout"},
    )
    dispatch_delivery(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == IntegrationDelivery.Status.UNCERTAIN
    assert delivery.attempts.count() == 1
    dispatch_delivery(delivery.id)
    assert delivery.attempts.count() == 1


def test_webhook_deduplicates_and_rejects_changed_replay():
    _, connection, _, endpoint = setup_integration()
    receipt, created = ingest_webhook(
        connection=connection,
        endpoint=endpoint,
        external_event_id="evt-1",
        contract_version=1,
        payload={"state": "ok"},
        authenticated=True,
    )
    assert created
    second, created = ingest_webhook(
        connection=connection,
        endpoint=endpoint,
        external_event_id="evt-1",
        contract_version=1,
        payload={"state": "ok"},
        authenticated=True,
    )
    assert not created and second.id == receipt.id
    with pytest.raises(IntegrationContractError):
        ingest_webhook(
            connection=connection,
            endpoint=endpoint,
            external_event_id="evt-1",
            contract_version=1,
            payload={"state": "changed"},
            authenticated=True,
        )


def test_reconciliation_resolves_uncertain_delivery():
    org, _, endpoint, _ = setup_integration()
    delivery = create_delivery(
        organization=org,
        endpoint=endpoint,
        source_type="order",
        source_id="3",
        source_version=1,
        operation_key="export",
        idempotency_key="idem-3",
        payload={"scenario": "timeout"},
    )
    dispatch_delivery(delivery.id)
    delivery.refresh_from_db()
    run = reconcile_delivery(delivery)
    delivery.refresh_from_db()
    assert run.status == "succeeded"
    assert delivery.status == "succeeded"


def test_cross_organization_endpoint_is_rejected():
    _, _, endpoint, _ = setup_integration()
    other = Organization.objects.create(name="Other", slug="other-integrations")
    with pytest.raises(IntegrationContractError):
        create_delivery(
            organization=other,
            endpoint=endpoint,
            source_type="order",
            source_id="4",
            source_version=1,
            operation_key="export",
            idempotency_key="idem-4",
            payload={},
        )
