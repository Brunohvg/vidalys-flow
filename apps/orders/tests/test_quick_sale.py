import uuid
from decimal import Decimal

import pytest

from apps.customers.models import Customer
from apps.fulfillment.models import Fulfillment, FulfillmentItem
from apps.orders.models import Order, OrderItem
from apps.orders.quick_services import create_quick_sale
from apps.organizations.models import OrganizationUnit
from apps.products.models import Product

pytestmark = pytest.mark.django_db


def test_manual_pickup_quick_sale_confirms_order_and_creates_fulfillment_idempotently(
    organization,
    user,
    operator_membership,
):
    unit = OrganizationUnit.objects.create(organization=organization, name="Balcão", is_active=True)
    command_id = str(uuid.uuid4())
    kwargs = {
        "organization": organization,
        "actor": user,
        "idempotency_key": command_id,
        "customer_name": "Cliente rápido",
        "pricing_mode": Order.PricingMode.MANUAL,
        "manual_total": Decimal("49.90"),
        "fulfillment_method": Fulfillment.Method.PICKUP,
        "pickup_unit": unit,
    }

    first_order, first_fulfillment = create_quick_sale(**kwargs)
    second_order, second_fulfillment = create_quick_sale(**kwargs)

    assert first_order.id == second_order.id
    assert first_fulfillment.id == second_fulfillment.id
    assert first_order.status == Order.Status.CONFIRMED
    assert first_order.total == Decimal("49.90")
    assert first_fulfillment.method == Fulfillment.Method.PICKUP
    assert first_fulfillment.status == Fulfillment.Status.DRAFT
    assert first_fulfillment.pickup_unit_id == unit.id
    assert Order.objects.filter(organization=organization).count() == 1
    assert Fulfillment.objects.filter(organization=organization).count() == 1
    assert Customer.objects.filter(organization=organization, display_name="Cliente rápido").count() == 1


def test_itemized_quick_sale_uses_selected_product_and_allocates_it(
    organization,
    user,
    operator_membership,
):
    unit = OrganizationUnit.objects.create(organization=organization, name="Balcão", is_active=True)
    product = Product.objects.create(organization=organization, name="Fita teste", default_unit="un")

    order, fulfillment = create_quick_sale(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer_name="Cliente itemizado",
        pricing_mode=Order.PricingMode.ITEMIZED,
        fulfillment_method=Fulfillment.Method.PICKUP,
        pickup_unit=unit,
        product=product,
        product_quantity=Decimal("2.000"),
        product_unit_price=Decimal("7.50"),
    )

    item = OrderItem.objects.get(order=order)
    allocation = FulfillmentItem.objects.get(fulfillment=fulfillment)
    assert order.status == Order.Status.CONFIRMED
    assert order.total == Decimal("15.00")
    assert item.product_id == product.id
    assert item.quantity == Decimal("2.000")
    assert allocation.order_item_id == item.id
    assert allocation.quantity == Decimal("2.000")


def test_delivery_quick_sale_freezes_address_before_fulfillment(
    organization,
    user,
    operator_membership,
):
    order, fulfillment = create_quick_sale(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer_name="Cliente entrega",
        pricing_mode=Order.PricingMode.MANUAL,
        manual_total=Decimal("80.00"),
        fulfillment_method=Fulfillment.Method.DELIVERY,
        has_delivery_address=True,
        delivery_postal_code="01001000",
        delivery_street="Praça da Sé",
        delivery_number="100",
        delivery_complement="",
        delivery_district="Sé",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    assert order.status == Order.Status.CONFIRMED
    assert order.shipping_address_snapshot["postal_code"] == "01001000"
    assert fulfillment.method == Fulfillment.Method.DELIVERY
    assert fulfillment.destination_snapshot == order.shipping_address_snapshot
