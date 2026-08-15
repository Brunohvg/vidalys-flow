import hashlib
import hmac
import json

from django.conf import settings
from django.db import transaction

from apps.platform.models import DataImportBatchReceipt, DataImportRowReceipt


class ImportReceiptConflict(ValueError):
    pass


def _private_digest(payload):
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def import_batch_digest(*, domain, headers, rows):
    canonical = {
        "domain": domain,
        "headers": list(headers),
        "rows": [
            {header: str(row.get(header) or "") for header in headers}
            for row in rows
        ],
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _private_digest(payload)


def import_row_digest(*, headers, row):
    canonical = {header: str(row.get(header) or "") for header in headers}
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _private_digest(payload)


@transaction.atomic
def claim_import_batch(*, organization, domain, source_digest, row_count):
    if domain not in DataImportBatchReceipt.Domain.values:
        raise ImportReceiptConflict("Domínio de importação inválido.")
    batch, created = DataImportBatchReceipt.objects.get_or_create(
        organization=organization,
        domain=domain,
        source_digest=source_digest,
        defaults={"row_count": row_count},
    )
    if created:
        return batch, True
    if batch.row_count != row_count:
        raise ImportReceiptConflict("Lote de importação inconsistente.")
    if batch.completed:
        return batch, False
    raise ImportReceiptConflict("Lote de importação já está em processamento.")


@transaction.atomic
def record_import_row(*, batch, row_number, row_digest, entity_id):
    if batch.completed:
        raise ImportReceiptConflict("Lote de importação já foi concluído.")
    receipt, created = DataImportRowReceipt.objects.get_or_create(
        batch=batch,
        row_number=row_number,
        defaults={
            "row_digest": row_digest,
            "entity_id": str(entity_id),
        },
    )
    if not created and (
        receipt.row_digest != row_digest
        or receipt.entity_id != str(entity_id)
    ):
        raise ImportReceiptConflict("Linha de importação inconsistente.")
    return receipt


@transaction.atomic
def complete_import_batch(*, batch):
    batch = DataImportBatchReceipt.objects.select_for_update().get(id=batch.id)
    if batch.completed:
        return batch
    if batch.rows.count() != batch.row_count:
        raise ImportReceiptConflict("Lote não possui evidência para todas as linhas.")
    batch.completed = True
    batch.save(update_fields=("completed", "updated_at"))
    return batch
