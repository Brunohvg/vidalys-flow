import uuid

import pytest
from django.urls import reverse

from apps.fulfillment.models import Fulfillment
from apps.fulfillment.services import create_fulfillment, transition_fulfillment

pytestmark = pytest.mark.django_db


def _ready_pickup(*, organization, confirmed_order, confirmed_item, pickup_unit, user):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method=Fulfillment.Method.PICKUP,
        allocations=[{"order_item": confirmed_item, "quantity": "1.000"}],
        pickup_unit=pickup_unit,
        idempotency_key=str(uuid.uuid4()),
    )
    for target in (Fulfillment.Status.PREPARING, Fulfillment.Status.READY):
        fulfillment = transition_fulfillment(
            organization=organization,
            fulfillment=fulfillment,
            actor=user,
            target_status=target,
            expected_version=fulfillment.version,
            idempotency_key=str(uuid.uuid4()),
        )
    return fulfillment


def test_generic_transition_cannot_complete_ready_pickup(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
    operator_membership,
):
    fulfillment = _ready_pickup(
        organization=organization,
        confirmed_order=confirmed_order,
        confirmed_item=confirmed_item,
        pickup_unit=pickup_unit,
        user=user,
    )
    client.force_login(user)

    response = client.post(
        reverse(
            "fulfillment:transition",
            args=(fulfillment.id, Fulfillment.Status.COMPLETED),
        ),
        {
            "expected_version": fulfillment.version,
            "idempotency_key": str(uuid.uuid4()),
        },
        follow=True,
    )

    fulfillment.refresh_from_db()
    assert response.status_code == 200
    assert fulfillment.status == Fulfillment.Status.READY
    assert "exige validação do código" in response.content.decode()


def test_ready_pickup_detail_has_no_direct_complete_form(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
    operator_membership,
):
    fulfillment = _ready_pickup(
        organization=organization,
        confirmed_order=confirmed_order,
        confirmed_item=confirmed_item,
        pickup_unit=pickup_unit,
        user=user,
    )
    client.force_login(user)

    response = client.get(reverse("fulfillment:detail", args=(fulfillment.id,)))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Validar retirada no pedido" in content
    assert f"/fulfillment/{fulfillment.id}/transition/completed/" not in content
