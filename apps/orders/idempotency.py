import hashlib
import json

from django.db import IntegrityError, transaction

from apps.orders.exceptions import IdempotencyConflict
from apps.orders.models import OrderCommandReceipt


def payload_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def claim_command(*, organization, operation, idempotency_key, payload, actor):
    key = str(idempotency_key).strip()
    if not key or len(key) > 64:
        raise IdempotencyConflict("Chave de idempotência inválida.")
    digest = payload_hash(payload)
    existing = (
        OrderCommandReceipt.objects.select_for_update()
        .filter(organization=organization, operation=operation, idempotency_key=key)
        .first()
    )
    if existing:
        _validate_existing(existing=existing, digest=digest)
        return existing, False
    try:
        with transaction.atomic():
            receipt = OrderCommandReceipt.objects.create(
                organization=organization,
                operation=operation,
                idempotency_key=key,
                request_hash=digest,
                actor=actor,
            )
        return receipt, True
    except IntegrityError:
        existing = OrderCommandReceipt.objects.select_for_update().get(
            organization=organization,
            operation=operation,
            idempotency_key=key,
        )
        _validate_existing(existing=existing, digest=digest)
        return existing, False


def _validate_existing(*, existing, digest):
    if existing.request_hash != digest:
        raise IdempotencyConflict("A chave de idempotência já foi usada com outro payload.")
    if not existing.completed:
        raise IdempotencyConflict("O comando idempotente ainda não foi concluído.")


def complete_command(*, receipt, order, item=None):
    receipt.order = order
    receipt.result_item_id = item.id if item else None
    receipt.resulting_version = order.version
    receipt.completed = True
    receipt.save(
        update_fields=("order", "result_item_id", "resulting_version", "completed", "updated_at"),
    )
    return receipt
