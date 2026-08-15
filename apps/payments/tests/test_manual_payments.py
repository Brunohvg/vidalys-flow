import uuid
from decimal import Decimal

import pytest

from apps.payments.exceptions import InvalidPayment
from apps.payments.manual_services import confirm_manual_payment
from apps.payments.models import PaymentIntent, PaymentStatusHistory
from apps.payments.services import create_payment_intent, request_hosted_checkout

pytestmark = pytest.mark.django_db


def _intent(*, organization, payable_order, manager):
    return create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )


def test_manual_pix_marks_intent_paid_with_immutable_history(organization, payable_order, manager):
    intent = _intent(organization=organization, payable_order=payable_order, manager=manager)
    key = str(uuid.uuid4())

    result = confirm_manual_payment(
        organization=organization,
        intent=intent,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=key,
        method="pix",
        amount=Decimal("125.40"),
    )

    assert result.status == PaymentIntent.Status.PAID
    assert result.paid_at is not None
    assert result.version == 2
    history = PaymentStatusHistory.objects.get(intent=result, command_id=key)
    assert history.source == "manual"
    assert history.reason_code == "manual_pix"


def test_manual_payment_is_idempotent(organization, payable_order, manager):
    intent = _intent(organization=organization, payable_order=payable_order, manager=manager)
    key = str(uuid.uuid4())
    kwargs = {
        "organization": organization,
        "intent": intent,
        "actor": manager,
        "expected_version": intent.version,
        "idempotency_key": key,
        "method": "cash",
        "amount": Decimal("125.40"),
    }

    first = confirm_manual_payment(**kwargs)
    second = confirm_manual_payment(**kwargs)

    assert first.id == second.id
    assert PaymentStatusHistory.objects.filter(intent=first, command_id=key).count() == 1


def test_manual_payment_rejects_amount_mismatch(organization, payable_order, manager):
    intent = _intent(organization=organization, payable_order=payable_order, manager=manager)

    with pytest.raises(InvalidPayment, match="corresponder exatamente"):
        confirm_manual_payment(
            organization=organization,
            intent=intent,
            actor=manager,
            expected_version=intent.version,
            idempotency_key=str(uuid.uuid4()),
            method="pix",
            amount=Decimal("120.00"),
        )


def test_manual_payment_rejects_open_hosted_checkout(
    organization,
    payable_order,
    manager,
    mercado_account,
):
    intent = _intent(organization=organization, payable_order=payable_order, manager=manager)
    request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=str(uuid.uuid4()),
    )
    intent.refresh_from_db()

    with pytest.raises(InvalidPayment, match="checkout externo ativo"):
        confirm_manual_payment(
            organization=organization,
            intent=intent,
            actor=manager,
            expected_version=intent.version,
            idempotency_key=str(uuid.uuid4()),
            method="card_present",
            amount=Decimal("125.40"),
        )
