import uuid
from decimal import Decimal

import pytest

from apps.fulfillment.exceptions import (
    FulfillmentPermissionDenied,
    IdempotencyConflict,
    InvalidFulfillment,
    InvalidTransition,
    OrganizationMismatch,
    VersionConflict,
)
from apps.fulfillment.models import (
    Fulfillment,
    FulfillmentCommandReceipt,
    FulfillmentStatusHistory,
)
from apps.fulfillment.services import create_fulfillment, replace_allocations, transition_fulfillment
from apps.organizations.models import Membership


def allocation(item, value):
    return [{"order_item": item, "quantity": value}]


@pytest.mark.django_db
def test_create_delivery_copies_snapshot_and_writes_evidence(
    organization, confirmed_order, confirmed_item, user
):
    key = str(uuid.uuid4())
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method=Fulfillment.Method.DELIVERY,
        allocations=allocation(confirmed_item, "4"),
        idempotency_key=key,
    )

    assert fulfillment.display_number == "PED-000010-F01"
    assert fulfillment.destination_snapshot == confirmed_order.shipping_address_snapshot
    assert fulfillment.destination_snapshot is not confirmed_order.shipping_address_snapshot
    assert fulfillment.items.get().quantity == Decimal("4.000")
    assert FulfillmentStatusHistory.objects.get(fulfillment=fulfillment).to_status == "draft"
    assert FulfillmentCommandReceipt.objects.get(idempotency_key=key).completed
    audit = organization.audit_events.get(entity_type="fulfillment")
    outbox = organization.outbox_events.get(event_type="fulfillment.created")
    assert "destination" not in audit.payload
    assert "destination" not in outbox.payload


@pytest.mark.django_db
def test_create_pickup_requires_same_active_unit(
    organization, confirmed_order, confirmed_item, pickup_unit, user
):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method=Fulfillment.Method.PICKUP,
        pickup_unit=pickup_unit,
        allocations=allocation(confirmed_item, "2"),
        idempotency_key=str(uuid.uuid4()),
    )
    assert fulfillment.pickup_unit == pickup_unit
    assert fulfillment.pickup_unit_name_snapshot == "Loja Centro"
    assert fulfillment.destination_snapshot == {}


@pytest.mark.django_db
def test_partial_batches_cannot_exceed_confirmed_quantity(
    organization, confirmed_order, confirmed_item, user
):
    create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=allocation(confirmed_item, "4"),
        idempotency_key=str(uuid.uuid4()),
    )
    with pytest.raises(InvalidFulfillment, match="excede"):
        create_fulfillment(
            organization=organization,
            order=confirmed_order,
            actor=user,
            method="delivery",
            allocations=allocation(confirmed_item, "7"),
            idempotency_key=str(uuid.uuid4()),
        )
    assert Fulfillment.objects.count() == 1


@pytest.mark.django_db
def test_cancelled_batch_releases_allocation(
    organization,
    confirmed_order,
    confirmed_item,
    user,
    manager,
    manager_membership,
):
    first = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=allocation(confirmed_item, "10"),
        idempotency_key=str(uuid.uuid4()),
    )
    transition_fulfillment(
        organization=organization,
        fulfillment=first,
        actor=manager,
        target_status="cancelled",
        reason="Cliente solicitou cancelamento",
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
    )
    second = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=allocation(confirmed_item, "10"),
        idempotency_key=str(uuid.uuid4()),
    )
    assert second.sequence == 2


@pytest.mark.django_db
def test_delivery_and_pickup_have_method_specific_lifecycles(
    organization, confirmed_order, confirmed_item, pickup_unit, user
):
    delivery = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=allocation(confirmed_item, "5"),
        idempotency_key=str(uuid.uuid4()),
    )
    pickup = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="pickup",
        pickup_unit=pickup_unit,
        allocations=allocation(confirmed_item, "5"),
        idempotency_key=str(uuid.uuid4()),
    )
    for target in ("preparing", "ready"):
        delivery = transition_fulfillment(
            organization=organization,
            fulfillment=delivery,
            actor=user,
            target_status=target,
            expected_version=delivery.version,
            idempotency_key=str(uuid.uuid4()),
        )
        pickup = transition_fulfillment(
            organization=organization,
            fulfillment=pickup,
            actor=user,
            target_status=target,
            expected_version=pickup.version,
            idempotency_key=str(uuid.uuid4()),
        )
    with pytest.raises(InvalidTransition, match="despachada"):
        transition_fulfillment(
            organization=organization,
            fulfillment=delivery,
            actor=user,
            target_status="completed",
            expected_version=delivery.version,
            idempotency_key=str(uuid.uuid4()),
        )
    delivery = transition_fulfillment(
        organization=organization,
        fulfillment=delivery,
        actor=user,
        target_status="in_transit",
        expected_version=delivery.version,
        idempotency_key=str(uuid.uuid4()),
    )
    delivery = transition_fulfillment(
        organization=organization,
        fulfillment=delivery,
        actor=user,
        target_status="completed",
        expected_version=delivery.version,
        idempotency_key=str(uuid.uuid4()),
    )
    pickup = transition_fulfillment(
        organization=organization,
        fulfillment=pickup,
        actor=user,
        target_status="completed",
        expected_version=pickup.version,
        idempotency_key=str(uuid.uuid4()),
    )
    assert delivery.status == pickup.status == "completed"


@pytest.mark.django_db
def test_idempotency_and_expected_version_are_enforced(
    organization, confirmed_order, confirmed_item, user
):
    key = str(uuid.uuid4())
    first = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=allocation(confirmed_item, "1"),
        idempotency_key=key,
    )
    repeated = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=allocation(confirmed_item, "1"),
        idempotency_key=key,
    )
    assert repeated.id == first.id
    with pytest.raises(IdempotencyConflict):
        create_fulfillment(
            organization=organization,
            order=confirmed_order,
            actor=user,
            method="delivery",
            allocations=allocation(confirmed_item, "2"),
            idempotency_key=key,
        )
    with pytest.raises(VersionConflict):
        replace_allocations(
            organization=organization,
            fulfillment=first,
            actor=user,
            allocations=allocation(confirmed_item, "2"),
            expected_version=99,
            idempotency_key=str(uuid.uuid4()),
        )


@pytest.mark.django_db
def test_operator_cannot_cancel_but_manager_can(
    organization,
    confirmed_order,
    confirmed_item,
    user,
    manager,
    manager_membership,
):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=allocation(confirmed_item, "1"),
        idempotency_key=str(uuid.uuid4()),
    )
    with pytest.raises(FulfillmentPermissionDenied):
        transition_fulfillment(
            organization=organization,
            fulfillment=fulfillment,
            actor=user,
            target_status="cancelled",
            reason="Tentativa",
            expected_version=1,
            idempotency_key=str(uuid.uuid4()),
        )
    cancelled = transition_fulfillment(
        organization=organization,
        fulfillment=fulfillment,
        actor=manager,
        target_status="cancelled",
        reason="Operação cancelada",
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
    )
    assert cancelled.status == "cancelled"


@pytest.mark.django_db
def test_cross_organization_order_and_unit_are_refused(
    organization,
    other_organization,
    confirmed_order,
    confirmed_item,
    user,
    outsider,
):
    Membership.objects.create(organization=other_organization, user=outsider, role=Membership.Role.OPERATOR)
    other_unit = organization.units.create(name="Unidade local")
    with pytest.raises(OrganizationMismatch):
        create_fulfillment(
            organization=other_organization,
            order=confirmed_order,
            actor=outsider,
            method="pickup",
            pickup_unit=other_unit,
            allocations=allocation(confirmed_item, "1"),
            idempotency_key=str(uuid.uuid4()),
        )


@pytest.mark.django_db
def test_history_and_items_refuse_direct_deletion(
    organization, confirmed_order, confirmed_item, user
):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=allocation(confirmed_item, "1"),
        idempotency_key=str(uuid.uuid4()),
    )
    with pytest.raises(TypeError):
        fulfillment.items.get().delete()
    with pytest.raises(TypeError):
        fulfillment.status_history.get().delete()
