import uuid

import pytest

from apps.fulfillment.models import Fulfillment, FulfillmentCommandReceipt
from apps.fulfillment.services import create_fulfillment
from apps.fulfillment.tasks import consume_order_cancellations
from apps.orders.services import cancel_order


@pytest.mark.django_db
def test_order_cancel_event_cancels_open_batches_once_and_preserves_completed(
    organization,
    confirmed_order,
    confirmed_item,
    user,
    manager,
    manager_membership,
):
    open_batch = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=[{"order_item": confirmed_item, "quantity": 5}],
        idempotency_key=str(uuid.uuid4()),
    )
    completed = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="pickup",
        pickup_unit=organization.units.create(name="Retirada"),
        allocations=[{"order_item": confirmed_item, "quantity": 5}],
        idempotency_key=str(uuid.uuid4()),
    )
    from apps.fulfillment.services import transition_fulfillment

    for target in ("preparing", "ready", "completed"):
        completed = transition_fulfillment(
            organization=organization,
            fulfillment=completed,
            actor=user,
            target_status=target,
            expected_version=completed.version,
            idempotency_key=str(uuid.uuid4()),
        )
    cancel_order(
        organization=organization,
        order=confirmed_order,
        actor=manager,
        reason="Cancelamento comercial",
        expected_version=confirmed_order.version,
        idempotency_key=str(uuid.uuid4()),
    )

    assert consume_order_cancellations() == 1
    assert consume_order_cancellations() == 0
    open_batch.refresh_from_db()
    completed.refresh_from_db()
    assert open_batch.status == Fulfillment.Status.CANCELLED
    assert open_batch.system_cancelled
    assert completed.status == Fulfillment.Status.COMPLETED
    assert FulfillmentCommandReceipt.objects.filter(operation="consume_order_cancelled_event").count() == 1
    audit = organization.audit_events.filter(action="fulfillment.cancelled", entity_id=str(open_batch.id)).get()
    assert "Cancelamento comercial" not in str(audit.payload)
