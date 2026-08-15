import uuid
from decimal import Decimal

import pytest

from apps.customers.models import Customer
from apps.orders.models import Order
from apps.orders.quick_services import create_quick_order


@pytest.mark.django_db
def test_quick_manual_order_creates_customer_and_preserves_manual_total(
    organization,
    user,
    operator_membership,
):
    order = create_quick_order(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer_name="Ana Ferreira",
        customer_phone="31999999999",
        pricing_mode=Order.PricingMode.MANUAL,
        manual_total=Decimal("180.00"),
    )

    assert order.customer.display_name == "Ana Ferreira"
    assert order.pricing_mode == Order.PricingMode.MANUAL
    assert order.manual_total == Decimal("180.00")
    assert order.subtotal == Decimal("180.00")
    assert order.total == Decimal("180.00")
    assert order.items.count() == 0


@pytest.mark.django_db
def test_quick_order_retry_does_not_duplicate_inline_customer(
    organization,
    user,
    operator_membership,
):
    key = str(uuid.uuid4())
    kwargs = {
        "organization": organization,
        "actor": user,
        "idempotency_key": key,
        "customer_name": "Cliente idempotente",
        "customer_phone": "31988887777",
        "pricing_mode": Order.PricingMode.MANUAL,
        "manual_total": Decimal("99.90"),
    }

    first = create_quick_order(**kwargs)
    second = create_quick_order(**kwargs)

    assert second.id == first.id
    assert Customer.objects.filter(organization=organization, display_name="Cliente idempotente").count() == 1
    assert Order.objects.filter(organization=organization).count() == 1


@pytest.mark.django_db
def test_quick_order_reuses_exact_document_without_name_merge(
    organization,
    user,
    operator_membership,
    customer,
):
    before = Customer.objects.filter(organization=organization).count()

    order = create_quick_order(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer_name="Nome diferente informado no balcão",
        customer_document="529.982.247-25",
        pricing_mode=Order.PricingMode.MANUAL,
        manual_total=Decimal("50.00"),
    )

    assert order.customer_id == customer.id
    assert Customer.objects.filter(organization=organization).count() == before


@pytest.mark.django_db
def test_itemized_quick_order_starts_without_manual_source(
    organization,
    user,
    operator_membership,
    customer,
):
    order = create_quick_order(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer=customer,
        pricing_mode=Order.PricingMode.ITEMIZED,
    )

    assert order.pricing_mode == Order.PricingMode.ITEMIZED
    assert order.manual_total is None
    assert order.total == Decimal("0.00")
