import threading

import pytest
from django.db import close_old_connections, connections

from apps.integrations.models import IntegrationConnection, IntegrationDelivery, IntegrationEndpoint
from apps.integrations.services import claim_delivery, create_delivery
from apps.organizations.models import Organization


@pytest.mark.django_db(transaction=True)
def test_concurrent_delivery_claims_create_exactly_one_active_attempt():
    organization = Organization.objects.create(name="Concurrency", slug="integrations-concurrency")
    connection = IntegrationConnection.objects.create(
        organization=organization,
        key="reference",
        status=IntegrationConnection.Status.ACTIVE,
    )
    endpoint = IntegrationEndpoint.objects.create(
        organization=organization,
        connection=connection,
        key="egress",
        direction=IntegrationEndpoint.Direction.EGRESS,
        contract_version=1,
        is_active=True,
    )
    delivery = create_delivery(
        organization=organization,
        endpoint=endpoint,
        source_type="order",
        source_id="concurrent",
        source_version=1,
        operation_key="export",
        idempotency_key="concurrent-claim",
        payload={"state": "confirmed"},
    )
    barrier = threading.Barrier(2)
    claimed = []
    errors = []

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            result = claim_delivery(delivery.id)
            if result is not None:
                claimed.append(result)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(claimed) == 1
    delivery.refresh_from_db()
    assert delivery.status == IntegrationDelivery.Status.SENDING
    assert delivery.attempts.filter(status="sending").count() == 1
