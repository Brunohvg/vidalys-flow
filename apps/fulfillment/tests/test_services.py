import uuid
import pytest

from decimal import Decimal

from apps.customers.services import create_customer
from apps.customers.models import Customer
from apps.orders.services import create_order, add_item, confirm_order
from apps.fulfillment.services import create_fulfillment


@pytest.mark.django_db
def test_create_fulfillment_idempotent(organization, user, operator_membership):
    customer = create_customer(
        organization=organization,
        actor=user,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente",
        document="52998224725",
    )
    order = create_order(organization=organization, customer=customer, actor=user, channel="web", idempotency_key=str(uuid.uuid4()))
    item = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=order.version,
        idempotency_key=str(uuid.uuid4()),
        quantity=Decimal("1"),
        unit_price=Decimal("10.00"),
        name="Item A",
        unit="un",
    )
    order.refresh_from_db()
    confirmed = confirm_order(
        organization=organization, order=order, actor=user, expected_version=order.version, idempotency_key=str(uuid.uuid4())
    )
    key = str(uuid.uuid4())
    f1 = create_fulfillment(
        organization=organization,
        order=confirmed,
        actor=user,
        method="delivery",
        allocations=[{"order_item_id": item.id, "quantity": Decimal("1")}],
        idempotency_key=key,
        destination_snapshot=confirmed.shipping_address_snapshot or {},
    )
    f2 = create_fulfillment(
        organization=organization,
        order=confirmed,
        actor=user,
        method="delivery",
        allocations=[{"order_item_id": item.id, "quantity": Decimal("1")}],
        idempotency_key=key,
        destination_snapshot=confirmed.shipping_address_snapshot or {},
    )
    assert f1.id == f2.id
    assert f1.items.count() == 1
    statuses = list(f1.status_history.all())
    assert statuses and statuses[0].to_status == f1.Status.DRAFT
