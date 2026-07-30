import uuid

import pytest
from django.urls import reverse

from apps.customers.models import Customer
from apps.orders.models import Order
from apps.orders.services import add_item


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
    detail = client.get(reverse("orders:detail", args=(order.id,)))
    assert "PED-000001" in detail.content.decode()


@pytest.mark.django_db
def test_operator_adjustment_submission_is_refused(client, organization, order, user, operator_membership):
    client.force_login(user)
    response = client.post(
        reverse("orders:add-item", args=(order.id,)),
        {
            "expected_version": 1,
            "idempotency_key": str(uuid.uuid4()),
            "name": "Item",
            "unit": "un",
            "quantity": "1",
            "unit_price": "10.00",
            "discount_amount": "1.00",
            "surcharge_amount": "0",
        },
        follow=True,
    )
    # Disabled adjustment fields are ignored by the form, so a forged
    # operator payload cannot apply the submitted discount.
    assert response.status_code == 200
    assert order.items.get().discount_amount == 0


@pytest.mark.django_db
def test_cross_organization_detail_is_404(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    hidden_customer = Customer.objects.create(
        organization=other_organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Oculto",
    )
    hidden = Order.objects.create(
        organization=other_organization,
        number=1,
        customer=hidden_customer,
        created_by=user,
    )
    client.force_login(user)
    assert client.get(reverse("orders:detail", args=(hidden.id,))).status_code == 404


@pytest.mark.django_db
def test_manager_can_cancel_from_view(
    client,
    organization,
    customer,
    manager,
    manager_membership,
):
    from apps.orders.services import create_order

    order = create_order(
        organization=organization,
        customer=customer,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    client.force_login(manager)
    response = client.post(
        reverse("orders:cancel", args=(order.id,)),
        {
            "expected_version": 1,
            "idempotency_key": str(uuid.uuid4()),
            "reason": "Cliente desistiu",
        },
    )
    order.refresh_from_db()
    assert response.status_code == 302
    assert order.status == Order.Status.CANCELLED


@pytest.mark.django_db
def test_stale_web_command_does_not_overwrite(client, organization, order, user, operator_membership):
    add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
        name="Existente",
        quantity=1,
        unit_price=10,
    )
    client.force_login(user)
    response = client.post(
        reverse("orders:add-item", args=(order.id,)),
        {
            "expected_version": 1,
            "idempotency_key": str(uuid.uuid4()),
            "name": "Concorrente",
            "unit": "un",
            "quantity": "1",
            "unit_price": "10",
            "discount_amount": "0",
            "surcharge_amount": "0",
        },
        follow=True,
    )
    assert "Pedido alterado por outro usuário" in response.content.decode()
    assert order.items.count() == 1
