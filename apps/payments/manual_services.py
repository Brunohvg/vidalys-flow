from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.payments.events import PAYMENT_STATUS_CHANGED
from apps.payments.exceptions import InvalidPayment
from apps.payments.idempotency import claim_command, complete_command
from apps.payments.models import PaymentAttempt, PaymentIntent
from apps.payments.services import (
    ACTIVE_ATTEMPT_STATUSES,
    _audit,
    _ensure_version,
    _history,
    _lock_intent,
    _outbox,
    _require_manager,
)

MANUAL_PAYMENT_METHODS = {
    "pix": "PIX",
    "cash": "Dinheiro",
    "card_present": "Cartão presencial",
    "bank_transfer": "Transferência",
    "other": "Outro",
}


def _existing_intent(receipt):
    intent = PaymentIntent.objects.filter(organization=receipt.organization, id=receipt.intent_id).first()
    if intent is None:
        raise InvalidPayment("O PaymentIntent resultante não existe.")
    return intent


@transaction.atomic
def confirm_manual_payment(
    *,
    organization,
    intent,
    actor,
    expected_version,
    idempotency_key,
    method,
    amount,
):
    """Confirm an offline payment without impersonating a provider result."""

    _require_manager(actor=actor, organization=organization)
    if method not in MANUAL_PAYMENT_METHODS:
        raise InvalidPayment("Forma de pagamento manual inválida.")

    amount = Decimal(amount).quantize(Decimal("0.01"))
    payload = {
        "intent_id": str(intent.id),
        "expected_version": expected_version,
        "method": method,
        "amount": str(amount),
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="confirm_manual_payment",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_intent(receipt)

    order, intent = _lock_intent(organization=organization, intent_id=intent.id)
    _ensure_version(intent=intent, expected_version=expected_version)

    if order.status != order.Status.CONFIRMED:
        raise InvalidPayment("Pagamento manual exige pedido confirmado e não cancelado.")
    if intent.status in {
        PaymentIntent.Status.PAID,
        PaymentIntent.Status.CANCELLED,
        PaymentIntent.Status.EXPIRED,
        PaymentIntent.Status.REQUIRES_ATTENTION,
    }:
        raise InvalidPayment("Estado atual do pagamento não permite confirmação manual.")
    if amount != intent.amount:
        raise InvalidPayment("O valor recebido deve corresponder exatamente ao PaymentIntent.")
    if PaymentAttempt.objects.filter(intent=intent, status__in=ACTIVE_ATTEMPT_STATUSES).exists():
        raise InvalidPayment("Feche o checkout externo ativo antes de confirmar pagamento manual.")

    before = intent.status
    intent.status = PaymentIntent.Status.PAID
    intent.paid_at = timezone.now()
    intent.version += 1
    intent.save(update_fields=("status", "paid_at", "version", "updated_at"))

    _history(
        intent=intent,
        from_status=before,
        actor=actor,
        command_id=idempotency_key,
        source="manual",
        reason_code=f"manual_{method}",
    )
    _audit(intent=intent, actor=actor, action=PAYMENT_STATUS_CHANGED)
    _outbox(intent=intent, event_type=PAYMENT_STATUS_CHANGED, command_id=idempotency_key)
    complete_command(receipt=receipt, intent=intent)
    return intent
