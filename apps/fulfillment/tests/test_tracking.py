import uuid

import pytest

from apps.fulfillment.exceptions import InvalidFulfillment
from apps.fulfillment.models import Fulfillment
from apps.fulfillment.tracking_services import set_tracking

pytestmark = pytest.mark.django_db


def _delivery(*, organization, confirmed_order, user, status=Fulfillment.Status.READY):
    return Fulfillment.objects.create(
        organization=organization,
        order=confirmed_order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        status=status,
        destination_snapshot=confirmed_order.shipping_address_snapshot,
        created_by=user,
    )


def test_ready_delivery_accepts_tracking_and_retry_is_idempotent(
    organization,
    confirmed_order,
    user,
    operator_membership,
):
    fulfillment = _delivery(
        organization=organization,
        confirmed_order=confirmed_order,
        user=user,
    )
    key = str(uuid.uuid4())
    kwargs = {
        "organization": organization,
        "fulfillment": fulfillment,
        "actor": user,
        "tracking_code": "BR123456789",
        "tracking_url": "https://tracking.example.test/BR123456789",
        "expected_version": fulfillment.version,
        "idempotency_key": key,
    }

    first = set_tracking(**kwargs)
    repeated = set_tracking(**kwargs)

    assert repeated.id == first.id
    assert first.tracking_code == "BR123456789"
    assert first.tracking_url == "https://tracking.example.test/BR123456789"
    assert first.version == 2
    first.refresh_from_db()
    assert first.version == 2


def test_pickup_rejects_tracking(
    organization,
    confirmed_order,
    pickup_unit,
    user,
    operator_membership,
):
    fulfillment = Fulfillment.objects.create(
        organization=organization,
        order=confirmed_order,
        sequence=1,
        method=Fulfillment.Method.PICKUP,
        status=Fulfillment.Status.READY,
        pickup_unit=pickup_unit,
        pickup_unit_name_snapshot=pickup_unit.name,
        created_by=user,
    )

    with pytest.raises(InvalidFulfillment, match="só pode ser configurado para entrega"):
        set_tracking(
            organization=organization,
            fulfillment=fulfillment,
            actor=user,
            tracking_code="NAO-DEVE-SALVAR",
            tracking_url="",
            expected_version=fulfillment.version,
            idempotency_key=str(uuid.uuid4()),
        )

    fulfillment.refresh_from_db()
    assert fulfillment.tracking_code == ""
    assert fulfillment.tracking_url == ""


def test_draft_delivery_rejects_tracking(
    organization,
    confirmed_order,
    user,
    operator_membership,
):
    fulfillment = _delivery(
        organization=organization,
        confirmed_order=confirmed_order,
        user=user,
        status=Fulfillment.Status.DRAFT,
    )

    with pytest.raises(InvalidFulfillment, match="pronta ou em trânsito"):
        set_tracking(
            organization=organization,
            fulfillment=fulfillment,
            actor=user,
            tracking_code="BR123",
            tracking_url="",
            expected_version=fulfillment.version,
            idempotency_key=str(uuid.uuid4()),
        )


def test_tracking_url_must_be_https(
    organization,
    confirmed_order,
    user,
    operator_membership,
):
    fulfillment = _delivery(
        organization=organization,
        confirmed_order=confirmed_order,
        user=user,
    )

    with pytest.raises(InvalidFulfillment, match="HTTPS"):
        set_tracking(
            organization=organization,
            fulfillment=fulfillment,
            actor=user,
            tracking_code="BR123",
            tracking_url="http://tracking.example.test/BR123",
            expected_version=fulfillment.version,
            idempotency_key=str(uuid.uuid4()),
        )
