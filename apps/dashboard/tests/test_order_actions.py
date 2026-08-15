import uuid
from decimal import Decimal

import pytest

from apps.dashboard.order_actions import order_next_action
from apps.payments.manual_services import confirm_manual_payment
from apps.payments.models import PixPaymentInstruction
from apps.payments.pix_services import configure_pix_instruction
from apps.payments.services import create_payment_intent

pytestmark = pytest.mark.django_db


def test_confirmed_order_without_payment_recommends_payment(
    organization,
    payable_order,
    manager,
    manager_membership,
):
    action = order_next_action(organization=organization, order=payable_order, user=manager)

    assert action["kind"] == "create_payment"
    assert action["can_operate"] is True


def test_pending_payment_exposes_only_same_organization_pix(
    organization,
    payable_order,
    manager,
    manager_membership,
):
    payment = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    pix = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.RANDOM,
        key_value="123e4567-e89b-12d3-a456-426614174000",
        beneficiary_name="Loja Exemplo",
    )

    action = order_next_action(organization=organization, order=payable_order, user=manager)

    assert action["kind"] == "payment_pending"
    assert action["payment"] == payment
    assert action["pix"] == pix


def test_paid_order_recommends_fulfillment_without_mutating_order(
    organization,
    payable_order,
    manager,
    manager_membership,
):
    payment = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    confirm_manual_payment(
        organization=organization,
        intent=payment,
        actor=manager,
        expected_version=payment.version,
        idempotency_key=str(uuid.uuid4()),
        method="cash",
        amount=Decimal("125.40"),
    )
    payable_order.refresh_from_db()

    action = order_next_action(organization=organization, order=payable_order, user=manager)

    assert action["kind"] == "create_fulfillment"
    assert payable_order.status == payable_order.Status.CONFIRMED


def test_cross_organization_order_has_no_next_action(
    other_organization,
    payable_order,
    manager,
):
    assert order_next_action(
        organization=other_organization,
        order=payable_order,
        user=manager,
    ) is None
