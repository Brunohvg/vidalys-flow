import uuid

import pytest
from django.urls import reverse

from apps.fulfillment.models import Fulfillment
from apps.fulfillment.services import create_fulfillment, transition_fulfillment

pytestmark = pytest.mark.django_db


def _delivery(*, organization, order, item, actor):
    return create_fulfillment(
        organization=organization,
        order=order,
        actor=actor,
        method=Fulfillment.Method.DELIVERY,
        allocations=[{"order_item": item, "quantity": item.quantity}],
        idempotency_key=str(uuid.uuid4()),
    )


def _pickup(*, organization, order, item, unit, actor):
    return create_fulfillment(
        organization=organization,
        order=order,
        actor=actor,
        method=Fulfillment.Method.PICKUP,
        pickup_unit=unit,
        allocations=[{"order_item": item, "quantity": item.quantity}],
        idempotency_key=str(uuid.uuid4()),
    )


def _transition(*, organization, fulfillment, actor, target):
    return transition_fulfillment(
        organization=organization,
        fulfillment=fulfillment,
        actor=actor,
        target_status=target,
        expected_version=fulfillment.version,
        idempotency_key=str(uuid.uuid4()),
    )


def test_operator_transitions_delivery_from_order_workspace(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    user,
    operator_membership,
):
    fulfillment = _delivery(
        organization=organization,
        order=confirmed_order,
        item=confirmed_item,
        actor=user,
    )
    client.force_login(user)

    response = client.post(
        reverse("fulfillment:workspace_transition", args=(fulfillment.id, Fulfillment.Status.PREPARING)),
        {
            "expected_version": fulfillment.version,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("orders:detail", args=(confirmed_order.id,))
    fulfillment.refresh_from_db()
    assert fulfillment.status == Fulfillment.Status.PREPARING


def test_workspace_does_not_bypass_pickup_code(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
    operator_membership,
):
    fulfillment = _pickup(
        organization=organization,
        order=confirmed_order,
        item=confirmed_item,
        unit=pickup_unit,
        actor=user,
    )
    fulfillment = _transition(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        target=Fulfillment.Status.PREPARING,
    )
    fulfillment = _transition(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        target=Fulfillment.Status.READY,
    )
    client.force_login(user)

    response = client.post(
        reverse("fulfillment:workspace_transition", args=(fulfillment.id, Fulfillment.Status.COMPLETED)),
        {
            "expected_version": fulfillment.version,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("orders:detail", args=(confirmed_order.id,))
    fulfillment.refresh_from_db()
    assert fulfillment.status == Fulfillment.Status.READY


def test_operator_updates_tracking_without_leaving_order(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    user,
    operator_membership,
):
    fulfillment = _delivery(
        organization=organization,
        order=confirmed_order,
        item=confirmed_item,
        actor=user,
    )
    fulfillment = _transition(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        target=Fulfillment.Status.PREPARING,
    )
    fulfillment = _transition(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        target=Fulfillment.Status.READY,
    )
    client.force_login(user)

    response = client.post(
        reverse("fulfillment:workspace_tracking", args=(fulfillment.id,)),
        {
            "tracking_code": "BR123456789",
            "tracking_url": "https://tracking.example.test/BR123456789",
            "expected_version": fulfillment.version,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("orders:detail", args=(confirmed_order.id,))
    fulfillment.refresh_from_db()
    assert fulfillment.tracking_code == "BR123456789"
    assert fulfillment.tracking_url == "https://tracking.example.test/BR123456789"


def test_order_workspace_renders_fulfillment_actions_and_tracking(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    user,
    operator_membership,
):
    fulfillment = _delivery(
        organization=organization,
        order=confirmed_order,
        item=confirmed_item,
        actor=user,
    )
    fulfillment = _transition(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        target=Fulfillment.Status.PREPARING,
    )
    fulfillment = _transition(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        target=Fulfillment.Status.READY,
    )
    client.force_login(user)

    response = client.get(reverse("orders:detail", args=(confirmed_order.id,)))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'id="fulfillment-workspace"' in html
    assert fulfillment.display_number in html
    assert "Marcar como enviado" in html
    assert "Adicionar rastreio" in html
    fulfillment_detail_url = reverse("fulfillment:detail", args=(fulfillment.id,))
    assert f'href="{fulfillment_detail_url}"' not in html
