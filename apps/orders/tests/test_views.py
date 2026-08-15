import uuid

import pytest
from django.urls import reverse

from apps.customers.models import Customer
from apps.orders.models import Order


@pytest.mark.django_db
def test_pages_require_authentication(client):
    assert client.get(reverse("orders:list")).status_code == 302


@pytest.mark.django_db
def test_list_is_scoped_and_paginated(client, organization, other_organization, user, operator_membership, customer):
    Order.objects.bulk_create(
        [
            Order(
                organization=organization,
                number=index,
                customer=customer,
                created_by=user,
            )
            for index in range(1, 27)
        ]
    )
    hidden_customer = Customer.objects.create(
        organization=other_organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Oculto",
    )
    Order.objects.create(
        organization=other_organization,
        number=1,
        customer=hidden_customer,
        created_by=user,
    )
    client.force_login(user)
    response = client.get(reverse("orders:list"))
    assert response.status_code == 200
    assert response.context["orders"].paginator.per_page == 25
    assert "Oculto" not in response.content.decode()


@pytest.mark.django_db
def test_list_accepts_valid_search_filter(client, organization, order, user, operator_membership):
    client.force_login(user)
    response = client.get(reverse("orders:list"), {"q": order.display_number})
    assert response.status_code == 200
    assert list(response.context["orders"].object_list) == [order]


@pytest.mark.django_db
def test_create_add_and_confirm_web_flow(client, organization, user, operator_membership, customer):
    client.force_login(user)
    response = client.post(
        reverse("orders:create"),
        {
            "customer": customer.id,
            "pricing_mode": Order.PricingMode.ITEMIZED,
            "channel": "balcão",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    order = Order.objects.get()
    assert response.status_code == 302
    response = client.post(
        reverse("orders:add-item", args=(order.id,)),
        {
            "expected_version": 1,
            "idempotency_key": str(uuid.uuid4()),
            "name": "Item avulso",
            "unit": "un",
            "quantity": "1",
            "unit_price": "10.00",
            "discount_amount": "0",
            "surcharge_amount": "0",
            "surcharge_reason": "",
            "notes": "",
        },
    )
    assert response.status_code == 302
    response = client.post(
        reverse("orders:confirm", args=(order.id,)),
        {"expected_version": 2, "idempotency_key": str(uuid.uuid4())},
    )
    order.refresh_from_db()
    assert response.status_code == 302
    assert order.status == Order.Status.CONFIRMED
