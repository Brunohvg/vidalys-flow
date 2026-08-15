import uuid

import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from apps.fulfillment import pickup_views
from apps.fulfillment.exceptions import FulfillmentPermissionDenied, InvalidFulfillment
from apps.fulfillment.models import Fulfillment
from apps.fulfillment.pickup_services import (
    complete_pickup_with_code,
    pickup_verification_code,
    reveal_pickup_code,
)
from apps.fulfillment.services import create_fulfillment, transition_fulfillment
from apps.organizations.models import Membership

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
    fulfillment = transition_fulfillment(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        target_status=Fulfillment.Status.PREPARING,
        expected_version=fulfillment.version,
        idempotency_key=str(uuid.uuid4()),
    )
    fulfillment = transition_fulfillment(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        target_status=Fulfillment.Status.READY,
        expected_version=fulfillment.version,
        idempotency_key=str(uuid.uuid4()),
    )
    return fulfillment


def test_valid_pickup_code_completes_through_canonical_transition(
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
    operator_membership,
):
    cache.clear()
    fulfillment = _ready_pickup(
        organization=organization,
        confirmed_order=confirmed_order,
        confirmed_item=confirmed_item,
        pickup_unit=pickup_unit,
        user=user,
    )
    code = pickup_verification_code(fulfillment=fulfillment)

    result = complete_pickup_with_code(
        organization=organization,
        fulfillment=fulfillment,
        actor=user,
        code=code,
        expected_version=fulfillment.version,
        idempotency_key=str(uuid.uuid4()),
    )

    assert result.status == Fulfillment.Status.COMPLETED
    assert result.completed_at is not None


def test_wrong_pickup_code_does_not_complete(
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
    operator_membership,
):
    cache.clear()
    fulfillment = _ready_pickup(
        organization=organization,
        confirmed_order=confirmed_order,
        confirmed_item=confirmed_item,
        pickup_unit=pickup_unit,
        user=user,
    )

    with pytest.raises(InvalidFulfillment, match="Código de retirada inválido"):
        complete_pickup_with_code(
            organization=organization,
            fulfillment=fulfillment,
            actor=user,
            code="000000",
            expected_version=fulfillment.version,
            idempotency_key=str(uuid.uuid4()),
        )

    fulfillment.refresh_from_db()
    assert fulfillment.status == Fulfillment.Status.READY


def test_operator_cannot_reveal_pickup_code(
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

    with pytest.raises(FulfillmentPermissionDenied):
        reveal_pickup_code(organization=organization, fulfillment=fulfillment, actor=user)


def test_manager_can_reveal_same_derived_code(
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
    operator_membership,
    manager,
    manager_membership,
):
    fulfillment = _ready_pickup(
        organization=organization,
        confirmed_order=confirmed_order,
        confirmed_item=confirmed_item,
        pickup_unit=pickup_unit,
        user=user,
    )

    assert reveal_pickup_code(
        organization=organization,
        fulfillment=fulfillment,
        actor=manager,
    ) == pickup_verification_code(fulfillment=fulfillment)


def test_other_organization_cannot_complete_pickup(
    organization,
    other_organization,
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

    with pytest.raises((FulfillmentPermissionDenied, InvalidFulfillment)):
        complete_pickup_with_code(
            organization=other_organization,
            fulfillment=fulfillment,
            actor=user,
            code=pickup_verification_code(fulfillment=fulfillment),
            expected_version=fulfillment.version,
            idempotency_key=str(uuid.uuid4()),
        )


def test_pickup_completion_http_success_and_invalid_code(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
    operator_membership,
):
    cache.clear()
    fulfillment = _ready_pickup(
        organization=organization,
        confirmed_order=confirmed_order,
        confirmed_item=confirmed_item,
        pickup_unit=pickup_unit,
        user=user,
    )
    url = reverse("fulfillment:complete_pickup", args=(fulfillment.id,))
    client.force_login(user)

    invalid = client.post(
        url,
        {
            "code": "000000",
            "expected_version": fulfillment.version,
            "idempotency_key": str(uuid.uuid4()),
        },
        follow=True,
    )
    fulfillment.refresh_from_db()
    assert invalid.status_code == 200
    assert fulfillment.status == Fulfillment.Status.READY
    assert "Código de retirada inválido" in invalid.content.decode()

    valid = client.post(
        url,
        {
            "code": pickup_verification_code(fulfillment=fulfillment),
            "expected_version": fulfillment.version,
            "idempotency_key": str(uuid.uuid4()),
        },
        follow=True,
    )
    fulfillment.refresh_from_db()
    assert valid.status_code == 200
    assert fulfillment.status == Fulfillment.Status.COMPLETED
    assert "Retirada confirmada" in valid.content.decode()


def test_pickup_completion_http_rejects_bad_form_and_cross_org(
    client,
    organization,
    other_organization,
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
    url = reverse("fulfillment:complete_pickup", args=(fulfillment.id,))
    bad_form = client.post(url, {"code": "12"}, follow=True)
    assert bad_form.status_code == 200
    assert "Código de retirada inválido" in bad_form.content.decode()

    other_user = type(user).objects.create_user("pickup-other@example.com", "safe-test-password")
    Membership.objects.create(
        organization=other_organization,
        user=other_user,
        role=Membership.Role.OPERATOR,
    )
    client.force_login(other_user)
    assert client.post(url, {}).status_code == 404


def test_pickup_completion_http_fails_closed_when_validation_backend_unavailable(
    client,
    organization,
    confirmed_order,
    confirmed_item,
    pickup_unit,
    user,
    operator_membership,
    monkeypatch,
):
    fulfillment = _ready_pickup(
        organization=organization,
        confirmed_order=confirmed_order,
        confirmed_item=confirmed_item,
        pickup_unit=pickup_unit,
        user=user,
    )
    monkeypatch.setattr(
        pickup_views,
        "complete_pickup_with_code",
        lambda **kwargs: (_ for _ in ()).throw(ImproperlyConfigured("cache unavailable")),
    )
    client.force_login(user)
    response = client.post(
        reverse("fulfillment:complete_pickup", args=(fulfillment.id,)),
        {
            "code": pickup_verification_code(fulfillment=fulfillment),
            "expected_version": fulfillment.version,
            "idempotency_key": str(uuid.uuid4()),
        },
        follow=True,
    )
    assert response.status_code == 200
    assert "temporariamente indisponível" in response.content.decode()
