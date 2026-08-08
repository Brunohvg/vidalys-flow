from decimal import Decimal

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.orders.models import Order, OrderItem
from apps.organizations.models import OrganizationUnit


@pytest.fixture
def confirmed_order(organization, user, operator_membership):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente Fulfillment",
    )
    return Order.objects.create(
        organization=organization,
        number=10,
        customer=customer,
        status=Order.Status.CONFIRMED,
        customer_name_snapshot=customer.display_name,
        shipping_address_snapshot={
            "schema_version": 1,
            "recipient_name": "Maria Operação",
            "postal_code": "01310100",
            "street": "Avenida Paulista",
            "number": "1000",
            "complement": "Sala 1",
            "district": "Bela Vista",
            "city": "São Paulo",
            "state": "SP",
            "country": "BR",
        },
        created_by=user,
        confirmed_at=timezone.now(),
    )


@pytest.fixture
def confirmed_item(organization, confirmed_order):
    return OrderItem.objects.create(
        organization=organization,
        order=confirmed_order,
        position=1,
        name_snapshot="Produto confirmado",
        sku_snapshot="SKU-F01",
        unit_snapshot="un",
        quantity=Decimal("10.000"),
        unit_price=Decimal("10.00"),
        gross_total=Decimal("100.00"),
        total=Decimal("100.00"),
    )


@pytest.fixture
def pickup_unit(organization):
    return OrganizationUnit.objects.create(organization=organization, name="Loja Centro")
