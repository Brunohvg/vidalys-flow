import hashlib
import json

from django.db import IntegrityError, transaction

from apps.payments.exceptions import IdempotencyConflict
from apps.payments.models import PaymentCommandReceipt


def payload_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def claim_command(*, organization, operation, idempotency_key, payload, actor=None, source_event_id=None):
    key = str(idempotency_key).strip()
    if not key or len(key) > 64:
        raise IdempotencyConflict("Chave de idempotência inválida.")
    digest = payload_hash(payload)
    existing = (
        PaymentCommandReceipt.objects.select_for_update()
        .filter(organization=organization, operation=operation, idempotency_key=key)
        .first()
    )
    if existing:
        _validate_existing(existing=existing, digest=digest)
        return existing, False
    try:
        with transaction.atomic():
            receipt = PaymentCommandReceipt.objects.create(
                organization=organization,
                operation=operation,
                idempotency_key=key,
                request_hash=digest,
                actor=actor,
                source_event_id=source_event_id,
            )
    except IntegrityError:
        receipt = PaymentCommandReceipt.objects.select_for_update().get(
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


def complete_command(*, receipt, intent, attempt=None):
    receipt.intent = intent
    receipt.attempt = attempt
    receipt.resulting_version = intent.version
    receipt.completed = True
    receipt.save(update_fields=("intent", "attempt", "resulting_version", "completed", "updated_at"))
