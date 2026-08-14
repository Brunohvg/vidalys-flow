from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.integrations.adapters import ReferenceAdapter
from apps.integrations.exceptions import (
    IntegrationAmbiguousError,
    IntegrationContractError,
    IntegrationPermanentError,
    IntegrationTransientError,
)
from apps.integrations.models import (
    IntegrationConnection,
    IntegrationDelivery,
    IntegrationEndpoint,
)
from apps.integrations.policies import can_configure_integrations, can_view_integrations
from apps.integrations.services import (
    claim_delivery,
    create_delivery,
    dispatch_delivery,
    ingest_webhook,
    reconcile_delivery,
    recover_expired_delivery_leases,
)
from apps.organizations.models import Membership, Organization
from apps.platform.models import OutboxEvent

pytestmark = pytest.mark.django_db
User = get_user_model()


def setup_integration(*, slug="org-integrations"):
    org = Organization.objects.create(name=slug, slug=slug)
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


def make_delivery(org, endpoint, *, source_id="1", idem="idem-1", payload=None):
    return create_delivery(
        organization=org,
        endpoint=endpoint,
        source_type="order",
        source_id=source_id,
        source_version=1,
        operation_key="export",
        idempotency_key=idem,
        payload=payload or {},
    )


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
    delivery = make_delivery(org, endpoint, payload={"state": "confirmed"})
    event = OutboxEvent.objects.get(
        organization=org,
        idempotency_key=f"integration-delivery:{delivery.id}:queued",
    )
    assert event.payload["delivery_id"] == str(delivery.id)
    assert event.payload["operation_key"] == "[REDACTED]"
    assert event.payload["event_contract_version"] == 1
    assert "state" not in event.payload
    dispatch_delivery(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == IntegrationDelivery.Status.SUCCEEDED
    assert delivery.attempts.get().external_id.startswith("ref-")


def test_payload_key_allowlist_rejects_arbitrary_or_nested_data():
    org, _, endpoint, _ = setup_integration()
    with pytest.raises(IntegrationContractError):
        make_delivery(
            org,
            endpoint,
            source_id="x",
            idem="bad-1",
            payload={"customer_email": "x@example.com"},
        )
    with pytest.raises(IntegrationContractError):
        make_delivery(
            org,
            endpoint,
            source_id="y",
            idem="bad-2",
            payload={"state": {"nested": "no"}},
        )


def test_reference_configuration_rejects_arbitrary_data_and_concrete_adapters():
    org = Organization.objects.create(name="Config", slug="config-integrations")
    with pytest.raises(ValidationError):
        IntegrationConnection.objects.create(
            organization=org,
            key="unsafe",
            config={"token": "must-not-be-here"},
        )
    with pytest.raises(ValidationError):
        IntegrationConnection.objects.create(
            organization=org,
            key="commercial",
            adapter_key="unapproved-provider",
        )


def test_ambiguous_acceptance_never_blind_retries():
    org, _, endpoint, _ = setup_integration()
    delivery = make_delivery(
        org,
        endpoint,
        source_id="2",
        idem="idem-2",
        payload={"scenario": "timeout"},
    )
    dispatch_delivery(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == IntegrationDelivery.Status.UNCERTAIN
    assert delivery.attempts.count() == 1
    dispatch_delivery(delivery.id)
    assert delivery.attempts.count() == 1


def test_expired_sending_lease_becomes_uncertain_instead_of_retrying():
    org, _, endpoint, _ = setup_integration()
    delivery = make_delivery(org, endpoint, source_id="lease", idem="lease-1")
    attempt_id = claim_delivery(delivery.id)
    attempt = delivery.attempts.get(id=attempt_id)
    attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
    attempt.save(update_fields=("lease_expires_at", "updated_at"))
    assert recover_expired_delivery_leases() == 1
    delivery.refresh_from_db()
    attempt.refresh_from_db()
    assert delivery.status == IntegrationDelivery.Status.UNCERTAIN
    assert attempt.status == "uncertain"
    assert attempt.result_code == "lease_expired"
    assert claim_delivery(delivery.id) is None


def test_transient_retry_is_bounded_and_circuit_breaker_degrades_connection():
    org, connection, endpoint, _ = setup_integration()
    delivery = make_delivery(
        org,
        endpoint,
        source_id="retry",
        idem="retry-1",
        payload={"scenario": "transient_failure"},
    )
    for sequence in range(1, 4):
        dispatch_delivery(delivery.id)
        delivery.refresh_from_db()
        connection.refresh_from_db()
        assert delivery.attempts.count() == sequence
        if sequence < 3:
            assert delivery.next_attempt_at is not None
            delivery.next_attempt_at = timezone.now() - timedelta(seconds=1)
            delivery.save(update_fields=("next_attempt_at", "updated_at"))
    assert connection.status == IntegrationConnection.Status.DEGRADED
    assert delivery.attempts.count() == 3
    assert dispatch_delivery(delivery.id) is None
    assert delivery.attempts.count() == 3


def test_permanent_failure_never_retries():
    org, _, endpoint, _ = setup_integration()
    delivery = make_delivery(
        org,
        endpoint,
        source_id="permanent",
        idem="permanent-1",
        payload={"scenario": "permanent_failure"},
    )
    dispatch_delivery(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == IntegrationDelivery.Status.FAILED
    assert delivery.next_attempt_at is None
    assert dispatch_delivery(delivery.id) is None
    assert delivery.attempts.count() == 1


def test_webhook_deduplicates_changed_replay_and_tracks_out_of_order():
    _, connection, _, endpoint = setup_integration()
    now = timezone.now()
    receipt, created = ingest_webhook(
        connection=connection,
        endpoint=endpoint,
        external_event_id="evt-1",
        contract_version=1,
        payload={"state": "ok"},
        authenticated=True,
        occurred_at=now,
    )
    assert created
    second, created = ingest_webhook(
        connection=connection,
        endpoint=endpoint,
        external_event_id="evt-1",
        contract_version=1,
        payload={"state": "ok"},
        authenticated=True,
        occurred_at=now,
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
            occurred_at=now,
        )
    older, created = ingest_webhook(
        connection=connection,
        endpoint=endpoint,
        external_event_id="evt-older",
        contract_version=1,
        payload={"state": "old"},
        authenticated=True,
        occurred_at=now - timedelta(seconds=30),
    )
    assert created and older.disposition == "out_of_order"


@pytest.mark.parametrize(
    "authenticated,version,occurred_delta",
    [
        (False, 1, timedelta()),
        (True, 2, timedelta()),
        (True, 1, -timedelta(minutes=6)),
        (True, 1, timedelta(minutes=2)),
    ],
)
def test_webhook_fails_closed_for_auth_version_and_replay_window(
    authenticated,
    version,
    occurred_delta,
):
    _, connection, _, endpoint = setup_integration()
    with pytest.raises(IntegrationContractError):
        ingest_webhook(
            connection=connection,
            endpoint=endpoint,
            external_event_id="evt-invalid",
            contract_version=version,
            payload={"state": "ok"},
            authenticated=authenticated,
            occurred_at=timezone.now() + occurred_delta,
        )


def test_reconciliation_resolves_uncertain_delivery():
    org, _, endpoint, _ = setup_integration()
    delivery = make_delivery(
        org,
        endpoint,
        source_id="3",
        idem="idem-3",
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
        make_delivery(other, endpoint, source_id="4", idem="idem-4")


def test_circuit_breaker_is_connection_scoped():
    org_a, connection_a, endpoint_a, _ = setup_integration(slug="org-a-integrations")
    org_b, connection_b, endpoint_b, _ = setup_integration(slug="org-b-integrations")
    connection_a.status = IntegrationConnection.Status.DEGRADED
    connection_a.save(update_fields=("status", "updated_at"))
    blocked = make_delivery(org_a, endpoint_a, source_id="a", idem="a-1")
    healthy = make_delivery(org_b, endpoint_b, source_id="b", idem="b-1")
    assert dispatch_delivery(blocked.id) is None
    dispatch_delivery(healthy.id)
    healthy.refresh_from_db()
    connection_b.refresh_from_db()
    assert healthy.status == IntegrationDelivery.Status.SUCCEEDED
    assert connection_b.status == IntegrationConnection.Status.ACTIVE


def test_permissions_require_active_membership_and_configuration_role():
    org = Organization.objects.create(name="Permissions", slug="permissions-integrations")
    owner = User.objects.create_user("integrations-owner@example.com")
    operator = User.objects.create_user("integrations-operator@example.com")
    inactive = User.objects.create_user("integrations-inactive@example.com")
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    Membership.objects.create(organization=org, user=operator, role=Membership.Role.OPERATOR)
    Membership.objects.create(
        organization=org,
        user=inactive,
        role=Membership.Role.ADMIN,
        is_active=False,
    )
    assert can_configure_integrations(owner, org)
    assert can_view_integrations(owner, org)
    assert not can_configure_integrations(operator, org)
    assert can_view_integrations(operator, org)
    assert not can_configure_integrations(inactive, org)
    assert not can_view_integrations(inactive, org)


def test_operational_view_is_organization_scoped(client):
    org_a, _, endpoint_a, _ = setup_integration(slug="view-a-integrations")
    org_b, _, endpoint_b, _ = setup_integration(slug="view-b-integrations")
    make_delivery(
        org_a,
        endpoint_a,
        source_id="tenant-a-visible-delivery",
        idem="visible-1",
        payload={"state": "tenant-a-private-state"},
    )
    make_delivery(
        org_b,
        endpoint_b,
        source_id="tenant-b-secret-delivery",
        idem="hidden-1",
        payload={"state": "tenant-b-private-state"},
    )
    user = User.objects.create_user("integrations-view@example.com")
    Membership.objects.create(organization=org_a, user=user, role=Membership.Role.OPERATOR)
    client.force_login(user)
    response = client.get("/integrations/")
    body = response.content.decode()
    assert response.status_code == 200
    assert "tenant-a-visible-delivery" in body
    assert "tenant-b-secret-delivery" not in body
    assert "tenant-a-private-state" not in body
    assert "tenant-b-private-state" not in body
