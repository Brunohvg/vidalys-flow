import uuid
from decimal import Decimal

import pytest

from apps.fulfillment.exceptions import InvalidFulfillment
from apps.fulfillment.forms import FulfillmentCreateForm
from apps.fulfillment.models import Fulfillment
from apps.fulfillment.services import create_fulfillment, replace_allocations
from apps.orders.models import Order

pytestmark = pytest.mark.django_db


def _make_manual(order, amount="50.00"):
    value = Decimal(amount)
    order.pricing_mode = Order.PricingMode.MANUAL
    order.manual_total = value
    order.subtotal = value
    order.discount_total = Decimal("0.00")
    order.surcharge_total = Decimal("0.00")
    order.total = value
    order.save(
        update_fields=(
            "pricing_mode",
            "manual_total",
            "subtotal",
            "discount_total",
            "surcharge_total",
            "total",
            "updated_at",
        )
    )
    return order


def test_manual_confirmed_order_without_items_can_create_pickup(
    organization,
    confirmed_order,
    pickup_unit,
    user,
):
    order = _make_manual(confirmed_order)

    fulfillment = create_fulfillment(
        organization=organization,
        order=order,
        actor=user,
        method=Fulfillment.Method.PICKUP,
        pickup_unit=pickup_unit,
        allocations=[],
        idempotency_key=str(uuid.uuid4()),
    )

    assert fulfillment.order_id == order.id
    assert fulfillment.method == Fulfillment.Method.PICKUP
    assert fulfillment.items.count() == 0
    assert fulfillment.pickup_unit == pickup_unit


def test_itemized_order_still_requires_allocations(
    organization,
    confirmed_order,
    pickup_unit,
    user,
):
    with pytest.raises(InvalidFulfillment, match="ao menos um item"):
        create_fulfillment(
            organization=organization,
            order=confirmed_order,
            actor=user,
            method=Fulfillment.Method.PICKUP,
            pickup_unit=pickup_unit,
            allocations=[],
            idempotency_key=str(uuid.uuid4()),
        )


def test_manual_order_with_items_still_requires_explicit_allocations(
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
):
    order = _make_manual(confirmed_order, amount="100.00")

    with pytest.raises(InvalidFulfillment, match="ao menos um item"):
        create_fulfillment(
            organization=organization,
            order=order,
            actor=user,
            method=Fulfillment.Method.PICKUP,
            pickup_unit=pickup_unit,
            allocations=[],
            idempotency_key=str(uuid.uuid4()),
        )


def test_manual_no_item_fulfillment_is_idempotent_and_can_keep_empty_allocations(
    organization,
    confirmed_order,
    pickup_unit,
    user,
):
    order = _make_manual(confirmed_order)
    key = str(uuid.uuid4())

    first = create_fulfillment(
        organization=organization,
        order=order,
        actor=user,
        method=Fulfillment.Method.PICKUP,
        pickup_unit=pickup_unit,
        allocations=[],
        idempotency_key=key,
    )
    repeated = create_fulfillment(
        organization=organization,
        order=order,
        actor=user,
        method=Fulfillment.Method.PICKUP,
        pickup_unit=pickup_unit,
        allocations=[],
        idempotency_key=key,
    )
    updated = replace_allocations(
        organization=organization,
        fulfillment=first,
        actor=user,
        allocations=[],
        expected_version=first.version,
        idempotency_key=str(uuid.uuid4()),
    )

    assert repeated.id == first.id
    assert updated.items.count() == 0
    assert updated.version == 2


def test_create_form_allows_empty_only_for_manual_order_without_items(
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
):
    itemized_form = FulfillmentCreateForm(
        data={
            "method": Fulfillment.Method.PICKUP,
            "pickup_unit": pickup_unit.id,
            "idempotency_key": str(uuid.uuid4()),
        },
        organization=organization,
        order=confirmed_order,
    )
    assert not itemized_form.is_valid()
    assert "Informe ao menos uma quantidade." in itemized_form.non_field_errors()

    confirmed_item.delete = None
    confirmed_item.__class__.objects.filter(pk=confirmed_item.pk).delete()
    manual_order = _make_manual(confirmed_order)
    manual_form = FulfillmentCreateForm(
        data={
            "method": Fulfillment.Method.PICKUP,
            "pickup_unit": pickup_unit.id,
            "idempotency_key": str(uuid.uuid4()),
        },
        organization=organization,
        order=manual_order,
    )
    assert manual_form.is_valid()
    assert manual_form.cleaned_data["allocations"] == []
