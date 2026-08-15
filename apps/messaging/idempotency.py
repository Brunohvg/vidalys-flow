import hashlib
import json

from django.db import IntegrityError, transaction

from apps.messaging.exceptions import IdempotencyConflict, MessagingPermissionDenied
from apps.messaging.models import MessageCommandReceipt
from apps.payments import policies as payment_policies


def payload_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _enforce_command_authorization(*, organization, operation, payload, actor):
    if operation != "create_message_from_command":
        return
    purpose = (payload or {}).get("purpose")
    if purpose == "checkout_link" and not payment_policies.can_operate_payments(
        user=actor,
        organization=organization,
    ):
        raise MessagingPermissionDenied("Compartilhar checkout exige permissão operacional de Payments.")


def claim_command(*, organization, operation, idempotency_key, payload, actor=None, source_event_id=None):
    _enforce_command_authorization(
        organization=organization,
        operation=operation,
        payload=payload,
        actor=actor,
    )
    key = str(idempotency_key).strip()
    if not key or len(key) > 64:
        raise IdempotencyConflict("Chave de idempotência inválida.")
    digest = payload_hash(payload)
    existing = (
        MessageCommandReceipt.objects.select_for_update()
        .filter(organization=organization, operation=operation, idempotency_key=key)
        .first()
    )
    if existing:
        _validate_existing(existing=existing, digest=digest)
        return existing, False
    try:
        with transaction.atomic():
            receipt = MessageCommandReceipt.objects.create(
                organization=organization,
                operation=operation,
                idempotency_key=key,
                request_hash=digest,
                actor=actor,
                source_event_id=source_event_id,
            )
    except IntegrityError:
        receipt = MessageCommandReceipt.objects.select_for_update().get(
            organization=organization,
            operation=operation,
            idempotency_key=key,
        )
        _validate_existing(existing=receipt, digest=digest)
        return receipt, False
    return receipt, True


def _validate_existing(*, existing, digest):
    if existing.request_hash != digest:
        raise IdempotencyConflict("A chave já foi usada com conteúdo diferente.")
    if not existing.completed:
        raise IdempotencyConflict("O comando idempotente anterior ainda não foi concluído.")


def complete_command(*, receipt, message=None, attempt=None, resulting_version=None):
    receipt.message = message
    receipt.attempt = attempt
    receipt.resulting_version = message.version if message is not None else resulting_version
    receipt.completed = True
    receipt.save(update_fields=("message", "attempt", "resulting_version", "completed", "updated_at"))
