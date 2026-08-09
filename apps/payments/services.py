import hashlib
from decimal import Decimal
from urllib.parse import urlparse

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.orders.models import Order
from apps.payments import policies
from apps.payments.events import (
    PAYMENT_CANCELLED,
    PAYMENT_CHECKOUT_ACTIVATED,
    PAYMENT_CHECKOUT_REQUESTED,
    PAYMENT_INTENT_CREATED,
    PAYMENT_REQUIRES_ATTENTION,
    PAYMENT_STATUS_CHANGED,
)
from apps.payments.exceptions import (
    IdempotencyConflict,
    InvalidPayment,
    OrganizationMismatch,
    PaymentPermissionDenied,
    VersionConflict,
)
from apps.payments.idempotency import claim_command, complete_command
from apps.payments.models import (
    PaymentAttempt,
    PaymentIntent,
    PaymentProviderAccount,
    PaymentStatusHistory,
    PaymentWebhookReceipt,
)
from apps.payments.providers import build_checkout_request, map_provider_status
from apps.platform.guardrails import require_external_effects_allowed
from apps.platform.services import enqueue_event

ACTIVE_ATTEMPT_STATUSES = {
    PaymentAttempt.Status.REQUESTED,
    PaymentAttempt.Status.ACTIVE,
    PaymentAttempt.Status.PROCESSING,
}
TERMINAL_INTENT_STATUSES = {
    PaymentIntent.Status.PAID,
    PaymentIntent.Status.CANCELLED,
    PaymentIntent.Status.EXPIRED,
}


def _require_manager(*, actor, organization):
    if actor is None or not policies.can_operate_payments(user=actor, organization=organization):
        raise PaymentPermissionDenied("Membership ativa de manager tier é obrigatória.")


def _lock_order(*, organization, order_id):
    order = Order.objects.select_for_update().filter(organization=organization, id=order_id).first()
    if order is None:
        raise OrganizationMismatch("Pedido não pertence à organização.")
    return order


def _lock_intent(*, organization, intent_id):
    ref = PaymentIntent.objects.filter(organization=organization, id=intent_id).values("order_id").first()
    if ref is None:
        raise OrganizationMismatch("Pagamento não pertence à organização.")
    order = _lock_order(organization=organization, order_id=ref["order_id"])
    intent = (
        PaymentIntent.objects.select_for_update()
        .select_related("order")
        .filter(organization=organization, id=intent_id)
        .first()
    )
    if intent is None or intent.order_id != order.id:
        raise OrganizationMismatch("Pagamento não pertence ao pedido da organização.")
    return order, intent


def _ensure_version(*, intent, expected_version):
    if intent.version != expected_version:
        raise VersionConflict(f"Pagamento alterado (versão atual {intent.version}, recebida {expected_version}).")


def _audit(*, intent, actor, action, payload=None):
    record_event(
        organization=intent.organization,
        actor=actor,
        action=action,
        entity_type="payment_intent",
        entity_id=intent.id,
        payload={
            "payment_intent_id": str(intent.id),
            "order_id": str(intent.order_id),
            "status": intent.status,
            "amount": str(intent.amount),
            "currency": intent.currency,
            "version": intent.version,
            **(payload or {}),
        },
    )


def _outbox(*, intent, event_type, command_id, extra=None):
    enqueue_event(
        organization=intent.organization,
        event_type=event_type,
        aggregate_type="payment_intent",
        aggregate_id=intent.id,
        payload={
            "payment_intent_id": str(intent.id),
            "order_id": str(intent.order_id),
            "status": intent.status,
            "amount": str(intent.amount),
            "currency": intent.currency,
            "version": intent.version,
            **(extra or {}),
        },
        idempotency_key=f"payment:{intent.id}:{event_type}:{command_id}",
    )


def _history(*, intent, from_status, actor, command_id, source, reason_code=""):
    PaymentStatusHistory.objects.create(
        organization=intent.organization,
        intent=intent,
        from_status=from_status,
        to_status=intent.status,
        actor=actor,
        command_id=str(command_id),
        source=source,
        reason_code=reason_code,
    )


def _existing_intent(receipt):
    intent = PaymentIntent.objects.filter(organization=receipt.organization, id=receipt.intent_id).first()
    if intent is None:
        raise IdempotencyConflict("O PaymentIntent resultante não existe.")
    return intent


def _existing_attempt(receipt):
    attempt = PaymentAttempt.objects.filter(organization=receipt.organization, id=receipt.attempt_id).first()
    if attempt is None:
        raise IdempotencyConflict("O PaymentAttempt resultante não existe.")
    return attempt


@transaction.atomic
def create_payment_intent(*, organization, order, actor, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    payload = {"order_id": str(order.id)}
    receipt, is_new = claim_command(
        organization=organization,
        operation="create_payment_intent",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_intent(receipt)
    order = _lock_order(organization=organization, order_id=order.id)
    if order.status != Order.Status.CONFIRMED:
        raise InvalidPayment("Somente pedido confirmado e não cancelado pode receber pagamento.")
    if order.currency != "BRL" or Decimal(order.total) <= 0:
        raise InvalidPayment("Pagamento exige total positivo em BRL.")
    if PaymentIntent.objects.filter(order=order).exists():
        raise InvalidPayment("O pedido já possui um PaymentIntent.")
    intent = PaymentIntent.objects.create(
        organization=organization,
        order=order,
        amount=order.total,
        currency=order.currency,
        order_number_snapshot=order.display_number,
        customer_name_snapshot=order.customer_name_snapshot,
        created_by=actor,
    )
    _history(
        intent=intent,
        from_status="",
        actor=actor,
        command_id=idempotency_key,
        source="command",
    )
    _audit(intent=intent, actor=actor, action=PAYMENT_INTENT_CREATED)
    _outbox(intent=intent, event_type=PAYMENT_INTENT_CREATED, command_id=idempotency_key)
    complete_command(receipt=receipt, intent=intent)
    return intent


@transaction.atomic
def request_hosted_checkout(*, organization, intent, provider_account, actor, expected_version, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    payload = {
        "intent_id": str(intent.id),
        "provider_account_id": str(provider_account.id),
        "expected_version": expected_version,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="request_hosted_checkout",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_attempt(receipt)
    order, intent = _lock_intent(organization=organization, intent_id=intent.id)
    _ensure_version(intent=intent, expected_version=expected_version)
    if order.status != Order.Status.CONFIRMED or intent.status != PaymentIntent.Status.PENDING:
        raise InvalidPayment("Pagamento não está elegível para novo checkout.")
    account = (
        PaymentProviderAccount.objects.select_for_update()
        .filter(organization=organization, id=provider_account.id, is_active=True)
        .first()
    )
    if account is None:
        raise OrganizationMismatch("Conta de provider não pertence à organização ou está inativa.")
    if (
        PaymentAttempt.objects.select_for_update()
        .filter(
            intent=intent,
            status__in=ACTIVE_ATTEMPT_STATUSES,
        )
        .exists()
    ):
        raise InvalidPayment("Já existe um checkout solicitado ou ativo.")
    attempt = PaymentAttempt.objects.create(
        organization=organization,
        intent=intent,
        provider_account=account,
        provider=account.provider,
        provider_idempotency_key=str(idempotency_key),
    )
    request = build_checkout_request(intent=intent, idempotency_key=str(idempotency_key))
    intent.version += 1
    intent.save(update_fields=("version", "updated_at"))
    _audit(
        intent=intent,
        actor=actor,
        action=PAYMENT_CHECKOUT_REQUESTED,
        payload={"provider": account.provider},
    )
    _outbox(
        intent=intent,
        event_type=PAYMENT_CHECKOUT_REQUESTED,
        command_id=idempotency_key,
        extra={
            "payment_attempt_id": str(attempt.id),
            "provider": account.provider,
            "amount_minor": request.amount_minor,
        },
    )
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return attempt


def dispatch_requested_checkout(*, attempt, adapter, idempotency_key):
    attempt = PaymentAttempt.objects.select_related("intent", "provider_account").filter(id=attempt.id).first()
    if attempt is None or attempt.status != PaymentAttempt.Status.REQUESTED:
        raise InvalidPayment("Tentativa não está aguardando envio.")
    if adapter.provider != attempt.provider:
        raise InvalidPayment("Adapter não corresponde ao provider da tentativa.")
    request = build_checkout_request(
        intent=attempt.intent,
        idempotency_key=attempt.provider_idempotency_key,
    )
    if getattr(adapter, "external", True):
        require_external_effects_allowed()
    result = adapter.create_checkout(request)
    return activate_hosted_checkout(
        organization=attempt.organization,
        attempt=attempt,
        result=result,
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def activate_hosted_checkout(*, organization, attempt, result, idempotency_key):
    payload = {
        "attempt_id": str(attempt.id),
        "external_resource_id": result.external_resource_id,
        "hosted_url_digest": hashlib.sha256(result.hosted_url.encode()).hexdigest(),
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="activate_hosted_checkout",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if not is_new:
        return _existing_attempt(receipt)
    order, intent = _lock_intent(organization=organization, intent_id=attempt.intent_id)
    attempt = (
        PaymentAttempt.objects.select_for_update()
        .filter(
            organization=organization,
            intent=intent,
            id=attempt.id,
        )
        .first()
    )
    if attempt is None:
        raise OrganizationMismatch("Tentativa não pertence à organização.")
    if order.status != Order.Status.CONFIRMED or attempt.status != PaymentAttempt.Status.REQUESTED:
        raise InvalidPayment("Tentativa não pode ser ativada.")
    parsed = urlparse(result.hosted_url)
    if parsed.scheme != "https" or not parsed.netloc or not result.external_resource_id:
        raise InvalidPayment("Resposta de checkout hospedado inválida.")
    attempt.external_resource_id = result.external_resource_id
    attempt.hosted_url = result.hosted_url
    attempt.expires_at = result.expires_at
    attempt.status = PaymentAttempt.Status.ACTIVE
    attempt.version += 1
    try:
        attempt.save(
            update_fields=("external_resource_id", "hosted_url", "expires_at", "status", "version", "updated_at")
        )
    except IntegrityError as exc:
        raise InvalidPayment("Identificador externo duplicado.") from exc
    from_status = intent.status
    intent.status = PaymentIntent.Status.AWAITING_PAYMENT
    intent.version += 1
    intent.save(update_fields=("status", "version", "updated_at"))
    _history(
        intent=intent,
        from_status=from_status,
        actor=None,
        command_id=idempotency_key,
        source="provider_worker",
    )
    _audit(intent=intent, actor=None, action=PAYMENT_CHECKOUT_ACTIVATED, payload={"provider": attempt.provider})
    _outbox(intent=intent, event_type=PAYMENT_CHECKOUT_ACTIVATED, command_id=idempotency_key)
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return attempt


def _canonical_transition(*, intent, attempt, target, command_id, source, reason_code=""):
    from_status = intent.status
    if target == "failed":
        attempt.status = PaymentAttempt.Status.FAILED
        intent.status = PaymentIntent.Status.PENDING
    elif target == PaymentIntent.Status.REQUIRES_ATTENTION:
        attempt.status = PaymentAttempt.Status.PROCESSING
        intent.status = PaymentIntent.Status.REQUIRES_ATTENTION
        intent.attention_code = reason_code or "provider_inconsistency"
    else:
        intent.status = target
        intent.attention_code = ""
        attempt.status = {
            PaymentIntent.Status.AWAITING_PAYMENT: PaymentAttempt.Status.ACTIVE,
            PaymentIntent.Status.PROCESSING: PaymentAttempt.Status.PROCESSING,
            PaymentIntent.Status.PAID: PaymentAttempt.Status.PAID,
            PaymentIntent.Status.CANCELLED: PaymentAttempt.Status.CANCELLED,
            PaymentIntent.Status.EXPIRED: PaymentAttempt.Status.EXPIRED,
        }[target]
    now = timezone.now()
    if intent.status == PaymentIntent.Status.PAID:
        intent.paid_at = now
    elif intent.status == PaymentIntent.Status.CANCELLED:
        intent.cancelled_at = now
    elif intent.status == PaymentIntent.Status.EXPIRED:
        intent.expired_at = now
    intent.version += 1
    attempt.version += 1
    intent.save(
        update_fields=(
            "status",
            "attention_code",
            "paid_at",
            "cancelled_at",
            "expired_at",
            "version",
            "updated_at",
        )
    )
    attempt.save(update_fields=("status", "version", "updated_at"))
    _history(
        intent=intent,
        from_status=from_status,
        actor=None,
        command_id=command_id,
        source=source,
        reason_code=reason_code,
    )


def _apply_resource_to_locked_attempt(*, intent, attempt, account, resource, command_id, source):
    target = map_provider_status(provider=account.provider, status=resource.status)
    reason_code = ""
    expected_minor = int(intent.amount * 100)
    if resource.currency != intent.currency or resource.amount_minor != expected_minor:
        target = PaymentIntent.Status.REQUIRES_ATTENTION
        reason_code = "amount_or_currency_mismatch"
    if intent.status in TERMINAL_INTENT_STATUSES and target != intent.status:
        target = PaymentIntent.Status.REQUIRES_ATTENTION
        reason_code = "non_monotonic_provider_event"
    changed = target != intent.status or target == "failed"
    if changed:
        _canonical_transition(
            intent=intent,
            attempt=attempt,
            target=target,
            command_id=command_id,
            source=source,
            reason_code=reason_code,
        )
    return changed, reason_code


@transaction.atomic
def apply_verified_provider_resource(*, provider_account, external_event_id, request_digest, resource):
    organization = provider_account.organization
    account = (
        PaymentProviderAccount.objects.select_for_update()
        .filter(
            organization=organization,
            id=provider_account.id,
            is_active=True,
            callbacks_enabled=True,
        )
        .first()
    )
    if account is None or account.provider != PaymentProviderAccount.Provider.MERCADO_PAGO:
        raise InvalidPayment("Callback não está habilitado para esta conta.")
    existing = PaymentWebhookReceipt.objects.filter(
        provider_account=account,
        external_event_id=external_event_id,
    ).first()
    if existing:
        return existing
    attempt_ref = (
        PaymentAttempt.objects.filter(
            organization=organization,
            provider_account=account,
            external_resource_id=resource.external_resource_id,
        )
        .values("intent_id")
        .first()
    )
    if attempt_ref is None:
        raise OrganizationMismatch("Recurso externo não pertence à conta configurada.")
    _, intent = _lock_intent(organization=organization, intent_id=attempt_ref["intent_id"])
    attempt = PaymentAttempt.objects.select_for_update().get(
        organization=organization,
        provider_account=account,
        external_resource_id=resource.external_resource_id,
    )
    command_id = hashlib.sha256(f"{account.id}:{external_event_id}".encode()).hexdigest()
    changed, reason_code = _apply_resource_to_locked_attempt(
        intent=intent,
        attempt=attempt,
        account=account,
        resource=resource,
        command_id=command_id,
        source="provider_callback",
    )
    if changed:
        event_type = (
            PAYMENT_REQUIRES_ATTENTION
            if intent.status == PaymentIntent.Status.REQUIRES_ATTENTION
            else PAYMENT_STATUS_CHANGED
        )
        _audit(
            intent=intent,
            actor=None,
            action=event_type,
            payload={"provider": account.provider, "reason_code": reason_code},
        )
        _outbox(intent=intent, event_type=event_type, command_id=command_id)
    receipt = PaymentWebhookReceipt.objects.create(
        organization=organization,
        provider_account=account,
        provider=account.provider,
        external_event_id=external_event_id,
        external_resource_id=resource.external_resource_id,
        request_digest=request_digest,
        canonical_result=intent.status,
        accepted=True,
    )
    return receipt


@transaction.atomic
def reconcile_verified_resource(*, organization, intent, actor, expected_version, idempotency_key, resource):
    _require_manager(actor=actor, organization=organization)
    payload = {
        "intent_id": str(intent.id),
        "expected_version": expected_version,
        "external_resource_id": resource.external_resource_id,
        "provider_status": resource.status,
        "amount_minor": resource.amount_minor,
        "currency": resource.currency,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="reconcile_payment",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_intent(receipt)
    _, intent = _lock_intent(organization=organization, intent_id=intent.id)
    _ensure_version(intent=intent, expected_version=expected_version)
    attempt = (
        PaymentAttempt.objects.select_for_update()
        .filter(
            organization=organization,
            intent=intent,
            external_resource_id=resource.external_resource_id,
        )
        .select_related("provider_account")
        .first()
    )
    if attempt is None:
        raise OrganizationMismatch("Recurso não pertence ao PaymentIntent da organização.")
    changed, reason_code = _apply_resource_to_locked_attempt(
        intent=intent,
        attempt=attempt,
        account=attempt.provider_account,
        resource=resource,
        command_id=idempotency_key,
        source="reconciliation",
    )
    if changed:
        event_type = (
            PAYMENT_REQUIRES_ATTENTION
            if intent.status == PaymentIntent.Status.REQUIRES_ATTENTION
            else PAYMENT_STATUS_CHANGED
        )
        _audit(
            intent=intent,
            actor=actor,
            action=event_type,
            payload={"provider": attempt.provider, "reason_code": reason_code},
        )
        _outbox(intent=intent, event_type=event_type, command_id=idempotency_key)
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return intent


def fetch_and_reconcile(*, organization, intent, actor, expected_version, idempotency_key, adapter):
    attempt = intent.attempts.filter(external_resource_id__gt="").order_by("-created_at").first()
    if attempt is None:
        raise InvalidPayment("Pagamento não possui recurso externo para reconciliar.")
    if adapter.provider != attempt.provider:
        raise InvalidPayment("Adapter não corresponde ao provider da tentativa.")
    if getattr(adapter, "external", True):
        require_external_effects_allowed()
    resource = adapter.fetch_resource(attempt.external_resource_id)
    return reconcile_verified_resource(
        organization=organization,
        intent=intent,
        actor=actor,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        resource=resource,
    )


@transaction.atomic
def consume_order_cancelled(*, organization, order_id, source_event_id):
    key = hashlib.sha256(f"{source_event_id}:{order_id}".encode()).hexdigest()
    payload = {"source_event_id": str(source_event_id), "order_id": str(order_id)}
    receipt, is_new = claim_command(
        organization=organization,
        operation="payment_consume_order_cancelled",
        idempotency_key=key,
        payload=payload,
        source_event_id=source_event_id,
    )
    if not is_new:
        return _existing_intent(receipt)
    order = _lock_order(organization=organization, order_id=order_id)
    if order.status != Order.Status.CANCELLED:
        raise InvalidPayment("Evento não corresponde a pedido cancelado.")
    intent = PaymentIntent.objects.select_for_update().filter(organization=organization, order=order).first()
    if intent is None:
        raise InvalidPayment("Pedido cancelado não possui PaymentIntent.")
    attempt = (
        PaymentAttempt.objects.select_for_update()
        .filter(
            intent=intent,
            status__in=ACTIVE_ATTEMPT_STATUSES,
        )
        .first()
    )
    if intent.status in {PaymentIntent.Status.PAID, PaymentIntent.Status.PROCESSING} or attempt:
        target = PaymentIntent.Status.REQUIRES_ATTENTION
        reason_code = "order_cancelled_with_open_or_paid_payment"
    elif intent.status in {PaymentIntent.Status.PENDING, PaymentIntent.Status.AWAITING_PAYMENT}:
        target = PaymentIntent.Status.CANCELLED
        reason_code = "order_cancelled"
    else:
        complete_command(receipt=receipt, intent=intent, attempt=attempt)
        return intent
    from_status = intent.status
    intent.status = target
    intent.attention_code = reason_code if target == PaymentIntent.Status.REQUIRES_ATTENTION else ""
    intent.cancelled_at = timezone.now() if target == PaymentIntent.Status.CANCELLED else intent.cancelled_at
    intent.version += 1
    intent.save(update_fields=("status", "attention_code", "cancelled_at", "version", "updated_at"))
    _history(
        intent=intent,
        from_status=from_status,
        actor=None,
        command_id=key,
        source="order_event",
        reason_code=reason_code,
    )
    event_type = PAYMENT_CANCELLED if target == PaymentIntent.Status.CANCELLED else PAYMENT_REQUIRES_ATTENTION
    _audit(intent=intent, actor=None, action=event_type, payload={"reason_code": reason_code})
    _outbox(intent=intent, event_type=event_type, command_id=key)
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return intent
