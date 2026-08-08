import uuid

import pytest
from django.urls import reverse

from apps.fulfillment.models import Fulfillment


@pytest.mark.django_db
def test_pages_require_authentication(client):
    assert client.get(reverse("fulfillment:list")).status_code == 302


@pytest.mark.django_db
def test_operator_can_create_and_advance_delivery_from_html(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    user,
    operator_membership,
):
    client.force_login(user)
    response = client.post(
        reverse("fulfillment:create", args=(confirmed_order.id,)),
        {
            "method": "delivery",
            "pickup_unit": "",
            f"quantity_{confirmed_item.id}": "2.000",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    fulfillment = Fulfillment.objects.get()
    assert response.status_code == 302
    detail = client.get(reverse("fulfillment:detail", args=(fulfillment.id,)))
    assert detail.status_code == 200
    assert "••••" in detail.content.decode()
    response = client.post(
        reverse("fulfillment:transition", args=(fulfillment.id, "preparing")),
        {"expected_version": 1, "idempotency_key": str(uuid.uuid4())},
    )
    fulfillment.refresh_from_db()
    assert response.status_code == 302
    assert fulfillment.status == "preparing"


@pytest.mark.django_db
def test_list_is_scoped_and_order_detail_links_fulfillment(
    client,
    organization,
    other_organization,
    confirmed_order,
    confirmed_item,
    user,
    operator_membership,
):
    client.force_login(user)
    client.post(
        reverse("fulfillment:create", args=(confirmed_order.id,)),
        {
            "method": "delivery",
            f"quantity_{confirmed_item.id}": "1.000",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    fulfillment = Fulfillment.objects.get()
    response = client.get(reverse("fulfillment:list"))
    assert fulfillment.display_number in response.content.decode()
    assert str(other_organization.id) not in response.content.decode()
    order_detail = client.get(reverse("orders:detail", args=(confirmed_order.id,)))
    assert fulfillment.display_number in order_detail.content.decode()
