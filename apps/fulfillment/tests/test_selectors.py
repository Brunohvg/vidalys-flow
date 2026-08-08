import uuid

import pytest

from apps.fulfillment.selectors import fulfillment_detail, search_fulfillments
from apps.fulfillment.services import create_fulfillment


@pytest.mark.django_db
def test_operator_receives_masked_destination(
    organization, confirmed_order, confirmed_item, user, operator_membership
):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=[{"order_item": confirmed_item, "quantity": 1}],
        idempotency_key=str(uuid.uuid4()),
    )
    detail = fulfillment_detail(
        organization=organization,
        fulfillment=fulfillment,
        user=user,
        membership=operator_membership,
    )
    assert detail["destination"]["street"] == "••••"
    assert detail["destination"]["city"] == "São Paulo"
    assert "Avenida Paulista" not in str(detail)


@pytest.mark.django_db
def test_manager_receives_unmasked_destination(
    organization,
    confirmed_order,
    confirmed_item,
    user,
    manager,
    manager_membership,
):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=[{"order_item": confirmed_item, "quantity": 1}],
        idempotency_key=str(uuid.uuid4()),
    )
    detail = fulfillment_detail(
        organization=organization,
        fulfillment=fulfillment,
        user=manager,
        membership=manager_membership,
    )
    assert detail["destination"]["street"] == "Avenida Paulista"


@pytest.mark.django_db
def test_search_is_scoped_to_organization(
    organization,
    other_organization,
    confirmed_order,
    confirmed_item,
    user,
):
    visible = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=[{"order_item": confirmed_item, "quantity": 1}],
        idempotency_key=str(uuid.uuid4()),
    )
    assert list(search_fulfillments(organization=organization, query="PED-000010")) == [visible]
    assert not search_fulfillments(organization=other_organization).exists()
