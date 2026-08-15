import uuid
from decimal import Decimal

import pytest

from apps.orders.exceptions import ConfirmationBlocked
from apps.orders.models import Order
from apps.orders.quick_services import create_quick_order
from apps.orders.services import add_item, confirm_order, create_order, remove_item, update_item

pytestmark = pytest.mark.django_db


def test_manual_order_keeps_manual_total_through_item_mutations_and_zero_item_confirmation(
    organization,
    user,
    operator_membership,
):
    order = create_quick_order(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer_name="Cliente manual",
        pricing_mode=Order.PricingMode.MANUAL,
        manual_total=Decimal("180.00"),
    )

    item = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=order.version,
        idempotency_key=str(uuid.uuid4()),
        name="Item informativo",
        unit="un",
        quantity="1",
        unit_price="50.00",
    )
    order.refresh_from_db()
    assert order.total == Decimal("180.00")
    assert order.subtotal == Decimal("180.00")

    item = update_item(
        organization=organization,
        item=item,
        actor=user,
        expected_version=order.version,
        idempotency_key=str(uuid.uuid4()),
        quantity="2",
    )
    order.refresh_from_db()
    assert item.total == Decimal("100.00")
    assert order.total == Decimal("180.00")

    remove_item(
        organization=organization,
        item=item,
        actor=user,
        expected_version=order.version,
        idempotency_key=str(uuid.uuid4()),
    )
    order.refresh_from_db()
    assert order.items.count() == 0
    assert order.total == Decimal("180.00")

    confirmed = confirm_order(
        organization=organization,
        order=order,
        actor=user,
        expected_version=order.version,
        idempotency_key=str(uuid.uuid4()),
    )
    assert confirmed.status == Order.Status.CONFIRMED
    assert confirmed.total == Decimal("180.00")
    assert confirmed.items.count() == 0


def test_itemized_order_without_items_remains_blocked(
    organization,
    customer,
    user,
    operator_membership,
):
    order = create_order(
        organization=organization,
        customer=customer,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
    )

    with pytest.raises(ConfirmationBlocked, match="sem itens"):
        confirm_order(
            organization=organization,
            order=order,
            actor=user,
            expected_version=order.version,
            idempotency_key=str(uuid.uuid4()),
        )
