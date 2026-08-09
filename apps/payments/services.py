import hashlib
import uuid
from datetime import timedelta
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
    PAYMENT_CHECKOUT_CANCELLATION_REQUESTED,
    PAYMENT_CHECKOUT_REOPENED,
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
from apps.platform.guardrails import ExternalEffectBlockedError, require_external_effects_allowed
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
DISPATCH_LEASE_SECONDS = 90
DISPATCH_RETRY_MAX_SECONDS = 300
ALLOWED_EVIDENCE_FLAGS = {
    "has_order_conflict",
    "has_provider_inconsistency",
}
MONOTONIC_PROVIDER_TRANSITIONS = {
    PaymentIntent.Status.PENDING: {
        PaymentIntent.Status.AWAITING_PAYMENT,
        PaymentIntent.Status.PROCESSING,
        PaymentIntent.Status.PAID,
        PaymentIntent.Status.CANCELLED,
        PaymentIntent.Status.EXPIRED,
        PaymentIntent.Status.REQUIRES_ATTENTION,
    },
    PaymentIntent.Status.AWAITING_PAYMENT: {
        PaymentIntent.Status.PROCESSING,
        PaymentIntent.Status.PAID,
        PaymentIntent.Status.CANCELLED,
        PaymentIntent.Status.EXPIRED,
        PaymentIntent.Status.REQUIRES_ATTENTION,
    },
    PaymentIntent.Status.PROCESSING: {
        PaymentIntent.Status.PAID,
        PaymentIntent.Status.CANCELLED,
        PaymentIntent.Status.EXPIRED,
        PaymentIntent.Status.REQUIRES_ATTENTION,
    },
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
    payload = payload or {}
    if set(payload) - ALLOWED_EVIDENCE_FLAGS or any(not isinstance(value, bool) for value in payload.values()):
        raise InvalidPayment("Payload de evidência financeira fora do schema aprovado.")
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
            **payload,
        },
    )


def _outbox(*, intent, event_type, command_id, extra=None):
    extra = extra or {}
    if set(extra) - ALLOWED_EVIDENCE_FLAGS or any(not isinstance(value, bool) for value in extra.values()):
        raise InvalidPayment("Payload de evento financeiro fora do schema aprovado.")
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
            **extra,
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
    account = PaymentProviderAccount.objects.filter(
        organization=organization,
        id=provider_account.id,
        is_active=True,
    ).first()
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
    intent.version += 1
    intent.save(update_fields=("version", "updated_at"))
    _audit(intent=intent, actor=actor, action=PAYMENT_CHECKOUT_REQUESTED)
    _outbox(
        intent=intent,
        event_type=PAYMENT_CHECKOUT_REQUESTED,
        command_id=idempotency_key,
    )
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return attempt


@transaction.atomic
def claim_requested_checkout(*, attempt_id):
    ref = PaymentAttempt.objects.filter(id=attempt_id).values("organization_id", "intent_id").first()
    if ref is None:
        raise InvalidPayment("Tentativa não está aguardando envio.")
    organization = ref["organization_id"]
    order, intent = _lock_intent(organization=organization, intent_id=ref["intent_id"])
    attempt = (
        PaymentAttempt.objects.select_for_update()
        .select_related("intent", "provider_account", "organization")
        .filter(id=attempt_id, organization=organization, intent=intent)
        .first()
    )
    if attempt is None or attempt.status != PaymentAttempt.Status.REQUESTED:
        raise InvalidPayment("Tentativa não está aguardando envio.")
    now = timezone.now()
    if attempt.dispatch_available_at and attempt.dispatch_available_at > now:
        raise InvalidPayment("Tentativa ainda está em espera controlada para nova tentativa.")
    if attempt.dispatch_lease_expires_at and attempt.dispatch_lease_expires_at > now:
        raise InvalidPayment("Tentativa já está reservada para envio.")
    error_code = ""
    if order.status != Order.Status.CONFIRMED:
        error_code = "order_not_confirmed"
        attempt.status = PaymentAttempt.Status.CANCELLED
    elif intent.status != PaymentIntent.Status.PENDING:
        error_code = "intent_not_pending"
        attempt.status = PaymentAttempt.Status.CANCELLED
    elif not PaymentProviderAccount.objects.filter(
        organization=organization,
        id=attempt.provider_account_id,
        is_active=True,
    ).exists():
        error_code = "provider_account_inactive"
        attempt.status = PaymentAttempt.Status.FAILED
    if error_code:
        attempt.dispatch_error_code = error_code
        attempt.version += 1
        attempt.save(update_fields=("status", "dispatch_error_code", "version", "updated_at"))
        command_id = f"dispatch-ineligible-{attempt.id}"
        if error_code == "order_not_confirmed" and intent.status not in TERMINAL_INTENT_STATUSES:
            from_status = intent.status
            intent.status = PaymentIntent.Status.CANCELLED
            intent.attention_code = ""
            intent.cancelled_at = now
            intent.version += 1
            intent.save(
                update_fields=("status", "attention_code", "cancelled_at", "version", "updated_at")
            )
            _history(
                intent=intent,
                from_status=from_status,
                actor=None,
                command_id=command_id,
                source="provider_worker",
                reason_code=error_code,
            )
            _audit(intent=intent, actor=None, action=PAYMENT_CANCELLED)
            _outbox(intent=intent, event_type=PAYMENT_CANCELLED, command_id=command_id)
        elif error_code == "provider_account_inactive" and intent.status == PaymentIntent.Status.PENDING:
            intent.version += 1
            intent.save(update_fields=("version", "updated_at"))
            _audit(intent=intent, actor=None, action=PAYMENT_STATUS_CHANGED)
            _outbox(intent=intent, event_type=PAYMENT_STATUS_CHANGED, command_id=command_id)
        return attempt
    attempt.dispatch_lease_token = uuid.uuid4()
    attempt.dispatch_lease_expires_at = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
    attempt.dispatch_attempts += 1
    attempt.dispatch_available_at = None
    attempt.dispatch_error_code = ""
    attempt.save(
        update_fields=(
            "dispatch_lease_token",
            "dispatch_lease_expires_at",
            "dispatch_attempts",
            "dispatch_available_at",
            "dispatch_error_code",
            "updated_at",
        )
    )
    return attempt


@transaction.atomic
def release_checkout_lease(*, attempt_id, lease_token, error_code=""):
    ref = PaymentAttempt.objects.filter(id=attempt_id).values("organization_id", "intent_id").first()
    if ref is None:
        return False
    organization = ref["organization_id"]
    _, intent = _lock_intent(organization=organization, intent_id=ref["intent_id"])
    attempt = PaymentAttempt.objects.select_for_update().filter(id=attempt_id, intent=intent).first()
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        return False
    attempt.dispatch_lease_token = None
    attempt.dispatch_lease_expires_at = None
    attempt.dispatch_error_code = error_code
    attempt.dispatch_available_at = (
        timezone.now()
        + timedelta(seconds=min(DISPATCH_RETRY_MAX_SECONDS, 5 * (2 ** min(attempt.dispatch_attempts, 6))))
        if error_code
        else None
    )
    attempt.save(
        update_fields=(
            "dispatch_lease_token",
            "dispatch_lease_expires_at",
            "dispatch_error_code",
            "dispatch_available_at",
            "updated_at",
        )
    )
    return True


def _dispatch_error_code(exc):
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ExternalEffectBlockedError):
        return "external_effect_blocked"
    if isinstance(exc, (ConnectionError, OSError)):
        return "transport_error"
    return "provider_error"


def dispatch_requested_checkout(*, attempt, adapter, idempotency_key):
    attempt = claim_requested_checkout(attempt_id=attempt.id)
    if attempt.status != PaymentAttempt.Status.REQUESTED:
        raise InvalidPayment("Tentativa tornou-se inelegível antes do envio.")
    if adapter.provider != attempt.provider:
        release_checkout_lease(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            error_code="provider_error",
        )
        raise InvalidPayment("Adapter não corresponde ao provider da tentativa.")
    try:
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
            lease_token=attempt.dispatch_lease_token,
        )
    except Exception as exc:
        release_checkout_lease(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            error_code=_dispatch_error_code(exc),
        )
        raise


@transaction.atomic
def activate_hosted_checkout(*, organization, attempt, result, idempotency_key, lease_token=None):
    parsed = urlparse(result.hosted_url)
    if parsed.scheme != "https" or not parsed.netloc or not result.external_resource_id:
        raise InvalidPayment("Resposta de checkout hospedado inválida.")
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
    result_after_local_cancel = (
        attempt.status == PaymentAttempt.Status.CANCELLED
        and attempt.dispatch_lease_token is not None
        and not attempt.external_resource_id
    )
    if attempt.status != PaymentAttempt.Status.REQUESTED and not result_after_local_cancel:
        raise InvalidPayment("Tentativa não pode ser ativada.")
    if attempt.dispatch_lease_token and attempt.dispatch_lease_token != lease_token:
        raise InvalidPayment("Lease de envio não pertence a este dispatcher.")
    context_changed = (
        order.status != Order.Status.CONFIRMED
        or intent.status != PaymentIntent.Status.PENDING
        or not PaymentProviderAccount.objects.filter(
            organization=organization,
            id=attempt.provider_account_id,
            is_active=True,
        ).exists()
    )
    attempt.external_resource_id = result.external_resource_id
    attempt.hosted_url = result.hosted_url
    attempt.expires_at = result.expires_at
    attempt.status = PaymentAttempt.Status.ACTIVE
    attempt.dispatch_lease_token = None
    attempt.dispatch_lease_expires_at = None
    attempt.dispatch_available_at = None
    attempt.dispatch_error_code = ""
    attempt.version += 1
    try:
        attempt.save(
            update_fields=(
                "external_resource_id",
                "hosted_url",
                "expires_at",
                "status",
                "dispatch_lease_token",
                "dispatch_lease_expires_at",
                "dispatch_available_at",
                "dispatch_error_code",
                "version",
                "updated_at",
            )
        )
    except IntegrityError as exc:
        raise InvalidPayment("Identificador externo duplicado.") from exc
    from_status = intent.status
    intent.status = (
        PaymentIntent.Status.REQUIRES_ATTENTION if context_changed else PaymentIntent.Status.AWAITING_PAYMENT
    )
    intent.attention_code = "dispatch_context_changed" if context_changed else ""
    intent.version += 1
    intent.save(update_fields=("status", "attention_code", "version", "updated_at"))
    _history(
        intent=intent,
        from_status=from_status,
        actor=None,
        command_id=idempotency_key,
        source="provider_worker",
        reason_code="dispatch_context_changed" if context_changed else "",
    )
    event_type = PAYMENT_REQUIRES_ATTENTION if context_changed else PAYMENT_CHECKOUT_ACTIVATED
    _audit(intent=intent, actor=None, action=event_type)
    _outbox(intent=intent, event_type=event_type, command_id=idempotency_key)
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return attempt


def _canonical_transition(*, intent, attempt, target, command_id, source, reason_code=""):
    from_status = intent.status
    if target == "failed":
        attempt.status = PaymentAttempt.Status.FAILED
        intent.status = PaymentIntent.Status.PENDING
        intent.attention_code = ""
    elif target == PaymentIntent.Status.REQUIRES_ATTENTION:
        if attempt.status not in {
            PaymentAttempt.Status.PAID,
            PaymentAttempt.Status.FAILED,
            PaymentAttempt.Status.CANCELLED,
            PaymentAttempt.Status.EXPIRED,
        }:
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
    terminal_attempt_target = {
        PaymentAttempt.Status.PAID: PaymentIntent.Status.PAID,
        PaymentAttempt.Status.FAILED: "failed",
        PaymentAttempt.Status.CANCELLED: PaymentIntent.Status.CANCELLED,
        PaymentAttempt.Status.EXPIRED: PaymentIntent.Status.EXPIRED,
    }.get(attempt.status)
    if terminal_attempt_target is not None and target != terminal_attempt_target:
        target = PaymentIntent.Status.REQUIRES_ATTENTION
        reason_code = "non_monotonic_provider_event"
    if intent.status == PaymentIntent.Status.REQUIRES_ATTENTION and source not in {
        "reconciliation",
        "cancellation_worker",
    }:
        return False, "requires_attention_locked"
    invalid_terminal_transition = intent.status in TERMINAL_INTENT_STATUSES and target != intent.status
    invalid_non_terminal_transition = (
        intent.status not in TERMINAL_INTENT_STATUSES
        and intent.status != PaymentIntent.Status.REQUIRES_ATTENTION
        and target != intent.status
        and target != "failed"
        and target not in MONOTONIC_PROVIDER_TRANSITIONS.get(intent.status, set())
    )
    if invalid_terminal_transition or invalid_non_terminal_transition:
        target = PaymentIntent.Status.REQUIRES_ATTENTION
        reason_code = "non_monotonic_provider_event"
    changed = (
        target == "failed"
        and (attempt.status != PaymentAttempt.Status.FAILED or intent.status != PaymentIntent.Status.PENDING)
    ) or (target != "failed" and target != intent.status)
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
def apply_verified_provider_resource(
    *,
    provider_account,
    external_event_id,
    authenticated_request_id_digest,
    request_digest,
    resource,
):
    organization = provider_account.organization
    account = PaymentProviderAccount.objects.filter(
        organization=organization,
        id=provider_account.id,
        is_active=True,
        callbacks_enabled=True,
    ).first()
    if account is None or account.provider != PaymentProviderAccount.Provider.MERCADO_PAGO:
        raise InvalidPayment("Callback não está habilitado para esta conta.")
    existing = PaymentWebhookReceipt.objects.filter(
        provider_account=account,
        external_resource_id=resource.external_resource_id,
        authenticated_request_id_digest=authenticated_request_id_digest,
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
    existing = PaymentWebhookReceipt.objects.filter(
        provider_account=account,
        external_resource_id=resource.external_resource_id,
        authenticated_request_id_digest=authenticated_request_id_digest,
    ).first()
    if existing:
        return existing
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
            payload={"has_provider_inconsistency": bool(reason_code)},
        )
        _outbox(
            intent=intent,
            event_type=event_type,
            command_id=command_id,
            extra={"has_provider_inconsistency": bool(reason_code)},
        )
    receipt = PaymentWebhookReceipt.objects.create(
        organization=organization,
        provider_account=account,
        provider=account.provider,
        external_event_id=external_event_id,
        external_resource_id=resource.external_resource_id,
        authenticated_request_id_digest=authenticated_request_id_digest,
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
            payload={"has_provider_inconsistency": bool(reason_code)},
        )
        _outbox(
            intent=intent,
            event_type=event_type,
            command_id=idempotency_key,
            extra={"has_provider_inconsistency": bool(reason_code)},
        )
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return intent


def fetch_and_reconcile(*, organization, intent, actor, expected_version, idempotency_key, adapter):
    _require_manager(actor=actor, organization=organization)
    scoped_intent = PaymentIntent.objects.filter(organization=organization, id=intent.id).first()
    if scoped_intent is None:
        raise OrganizationMismatch("Pagamento não pertence à organização.")
    attempt = (
        PaymentAttempt.objects.select_related("provider_account")
        .filter(organization=organization, intent=scoped_intent, external_resource_id__gt="")
        .order_by("-created_at")
        .first()
    )
    if attempt is None:
        raise InvalidPayment("Pagamento não possui recurso externo para reconciliar.")
    if not attempt.provider_account.is_active:
        raise InvalidPayment("Conta de provider está inativa.")
    if adapter.provider != attempt.provider:
        raise InvalidPayment("Adapter não corresponde ao provider da tentativa.")
    if getattr(adapter, "external", True):
        require_external_effects_allowed()
    resource = adapter.fetch_resource(attempt.external_resource_id)
    return reconcile_verified_resource(
        organization=organization,
        intent=scoped_intent,
        actor=actor,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        resource=resource,
    )


@transaction.atomic
def request_hosted_checkout_cancellation(*, organization, intent, actor, expected_version, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    payload = {"intent_id": str(intent.id), "expected_version": expected_version}
    receipt, is_new = claim_command(
        organization=organization,
        operation="request_hosted_checkout_cancellation",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_attempt(receipt)
    _, intent = _lock_intent(organization=organization, intent_id=intent.id)
    _ensure_version(intent=intent, expected_version=expected_version)
    attempt = (
        PaymentAttempt.objects.select_for_update()
        .filter(organization=organization, intent=intent, status__in=ACTIVE_ATTEMPT_STATUSES)
        .order_by("-created_at")
        .first()
    )
    if attempt is None:
        raise InvalidPayment("Pagamento não possui checkout aberto para cancelar.")
    if attempt.status == PaymentAttempt.Status.REQUESTED and attempt.dispatch_lease_token is None:
        attempt.status = PaymentAttempt.Status.CANCELLED
        attempt.dispatch_lease_token = None
        attempt.dispatch_lease_expires_at = None
        attempt.dispatch_available_at = None
        attempt.dispatch_error_code = "cancelled_before_dispatch"
        attempt.version += 1
        attempt.save(
            update_fields=(
                "status",
                "dispatch_lease_token",
                "dispatch_lease_expires_at",
                "dispatch_available_at",
                "dispatch_error_code",
                "version",
                "updated_at",
            )
        )
    else:
        _outbox(
            intent=intent,
            event_type=PAYMENT_CHECKOUT_CANCELLATION_REQUESTED,
            command_id=idempotency_key,
        )
    intent.version += 1
    intent.save(update_fields=("version", "updated_at"))
    _audit(intent=intent, actor=actor, action=PAYMENT_CHECKOUT_CANCELLATION_REQUESTED)
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return attempt


@transaction.atomic
def claim_checkout_cancellation(*, attempt_id):
    ref = PaymentAttempt.objects.filter(id=attempt_id).values("organization_id", "intent_id").first()
    if ref is None:
        raise InvalidPayment("Tentativa de cancelamento não encontrada.")
    _, intent = _lock_intent(organization=ref["organization_id"], intent_id=ref["intent_id"])
    attempt = (
        PaymentAttempt.objects.select_for_update()
        .select_related("organization", "intent", "provider_account")
        .filter(
            id=attempt_id, intent=intent, status__in=(PaymentAttempt.Status.ACTIVE, PaymentAttempt.Status.PROCESSING)
        )
        .first()
    )
    if attempt is None or not attempt.external_resource_id:
        raise InvalidPayment("Tentativa não possui checkout externo cancelável.")
    now = timezone.now()
    if attempt.dispatch_available_at and attempt.dispatch_available_at > now:
        raise InvalidPayment("Cancelamento ainda está em espera controlada.")
    if attempt.dispatch_lease_expires_at and attempt.dispatch_lease_expires_at > now:
        raise InvalidPayment("Tentativa já está reservada.")
    attempt.dispatch_lease_token = uuid.uuid4()
    attempt.dispatch_lease_expires_at = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
    attempt.dispatch_attempts += 1
    attempt.dispatch_available_at = None
    attempt.dispatch_error_code = ""
    attempt.save(
        update_fields=(
            "dispatch_lease_token",
            "dispatch_lease_expires_at",
            "dispatch_attempts",
            "dispatch_available_at",
            "dispatch_error_code",
            "updated_at",
        )
    )
    return attempt


@transaction.atomic
def apply_verified_checkout_cancellation(*, organization, attempt, resource, idempotency_key, lease_token):
    _, intent = _lock_intent(organization=organization, intent_id=attempt.intent_id)
    attempt = (
        PaymentAttempt.objects.select_for_update()
        .select_related("provider_account")
        .filter(organization=organization, intent=intent, id=attempt.id)
        .first()
    )
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        raise InvalidPayment("Lease de cancelamento inválido.")
    if resource.external_resource_id != attempt.external_resource_id:
        raise OrganizationMismatch("Resposta não pertence ao checkout cancelado.")
    target = map_provider_status(provider=attempt.provider, status=resource.status)
    if target not in {PaymentIntent.Status.CANCELLED, PaymentIntent.Status.EXPIRED}:
        raise InvalidPayment("Provider ainda não confirmou o fechamento do checkout.")
    changed, reason_code = _apply_resource_to_locked_attempt(
        intent=intent,
        attempt=attempt,
        account=attempt.provider_account,
        resource=resource,
        command_id=idempotency_key,
        source="cancellation_worker",
    )
    attempt.dispatch_lease_token = None
    attempt.dispatch_lease_expires_at = None
    attempt.dispatch_available_at = None
    attempt.dispatch_error_code = ""
    attempt.save(
        update_fields=(
            "dispatch_lease_token",
            "dispatch_lease_expires_at",
            "dispatch_available_at",
            "dispatch_error_code",
            "updated_at",
        )
    )
    if changed:
        event_type = (
            PAYMENT_REQUIRES_ATTENTION
            if intent.status == PaymentIntent.Status.REQUIRES_ATTENTION
            else PAYMENT_CANCELLED
        )
        _audit(
            intent=intent,
            actor=None,
            action=event_type,
            payload={"has_provider_inconsistency": bool(reason_code)},
        )
        _outbox(
            intent=intent,
            event_type=event_type,
            command_id=idempotency_key,
            extra={"has_provider_inconsistency": bool(reason_code)},
        )
    return attempt


def dispatch_checkout_cancellation(*, attempt, adapter, idempotency_key):
    attempt = claim_checkout_cancellation(attempt_id=attempt.id)
    if adapter.provider != attempt.provider:
        release_checkout_lease(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            error_code="provider_error",
        )
        raise InvalidPayment("Adapter não corresponde ao provider da tentativa.")
    try:
        if getattr(adapter, "external", True):
            require_external_effects_allowed()
        resource = adapter.cancel_checkout(
            attempt.external_resource_id,
            idempotency_key=attempt.provider_idempotency_key,
        )
        return apply_verified_checkout_cancellation(
            organization=attempt.organization,
            attempt=attempt,
            resource=resource,
            idempotency_key=idempotency_key,
            lease_token=attempt.dispatch_lease_token,
        )
    except Exception as exc:
        release_checkout_lease(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            error_code=_dispatch_error_code(exc),
        )
        raise


@transaction.atomic
def reopen_payment_after_verified_closure(*, organization, intent, actor, expected_version, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    payload = {"intent_id": str(intent.id), "expected_version": expected_version}
    receipt, is_new = claim_command(
        organization=organization,
        operation="reopen_payment_after_verified_closure",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_intent(receipt)
    order, intent = _lock_intent(organization=organization, intent_id=intent.id)
    _ensure_version(intent=intent, expected_version=expected_version)
    if order.status != Order.Status.CONFIRMED:
        raise InvalidPayment("Pedido precisa permanecer confirmado para reabrir o pagamento.")
    if PaymentAttempt.objects.select_for_update().filter(intent=intent, status__in=ACTIVE_ATTEMPT_STATUSES).exists():
        raise InvalidPayment("Ainda existe uma tentativa aberta.")
    last_attempt = PaymentAttempt.objects.filter(intent=intent).order_by("-created_at").first()
    if last_attempt is None or last_attempt.status not in {
        PaymentAttempt.Status.FAILED,
        PaymentAttempt.Status.CANCELLED,
        PaymentAttempt.Status.EXPIRED,
    }:
        raise InvalidPayment("A tentativa anterior ainda não possui fechamento verificado.")
    if intent.status not in {
        PaymentIntent.Status.PENDING,
        PaymentIntent.Status.CANCELLED,
        PaymentIntent.Status.EXPIRED,
    }:
        raise InvalidPayment("Pagamento não pode ser reaberto neste estado.")
    from_status = intent.status
    intent.status = PaymentIntent.Status.PENDING
    intent.attention_code = ""
    intent.cancelled_at = None
    intent.expired_at = None
    intent.version += 1
    intent.save(update_fields=("status", "attention_code", "cancelled_at", "expired_at", "version", "updated_at"))
    if from_status != intent.status:
        _history(
            intent=intent,
            from_status=from_status,
            actor=actor,
            command_id=idempotency_key,
            source="command",
            reason_code="verified_attempt_closed",
        )
    _audit(intent=intent, actor=actor, action=PAYMENT_CHECKOUT_REOPENED)
    _outbox(intent=intent, event_type=PAYMENT_CHECKOUT_REOPENED, command_id=idempotency_key)
    complete_command(receipt=receipt, intent=intent, attempt=last_attempt)
    return intent


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
    requested_without_inflight_io = bool(
        attempt and attempt.status == PaymentAttempt.Status.REQUESTED and attempt.dispatch_lease_token is None
    )
    if requested_without_inflight_io:
        attempt.status = PaymentAttempt.Status.CANCELLED
        attempt.dispatch_error_code = "order_cancelled"
        attempt.version += 1
        attempt.save(update_fields=("status", "dispatch_error_code", "version", "updated_at"))
        target = PaymentIntent.Status.CANCELLED
        reason_code = "order_cancelled"
    elif intent.status in {PaymentIntent.Status.PAID, PaymentIntent.Status.PROCESSING} or attempt:
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
    conflict = target == PaymentIntent.Status.REQUIRES_ATTENTION
    _audit(intent=intent, actor=None, action=event_type, payload={"has_order_conflict": conflict})
    _outbox(
        intent=intent,
        event_type=event_type,
        command_id=key,
        extra={"has_order_conflict": conflict},
    )
    complete_command(receipt=receipt, intent=intent, attempt=attempt)
    return intent
