import uuid

import pytest

from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.orders.services import create_order


@pytest.fixture
def customer(organization, user, operator_membership):
    return create_customer(
        organization=organization,
        actor=user,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente do pedido",
        document="52998224725",
    )


@pytest.fixture
def order(organization, customer, user):
    return create_order(
        organization=organization,
        customer=customer,
        actor=user,
        channel="whatsapp",
        idempotency_key=str(uuid.uuid4()),
    )
