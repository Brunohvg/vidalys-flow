import pytest

from apps.platform.import_receipts import (
    ImportReceiptConflict,
    claim_import_batch,
    complete_import_batch,
    import_batch_digest,
    import_row_digest,
    record_import_row,
)
from apps.platform.models import DataImportBatchReceipt

pytestmark = pytest.mark.django_db


HEADERS = ("display_name", "document")
ROWS = [
    {"display_name": "Cliente Sensível", "document": "52998224725"},
    {"display_name": "Outro Cliente", "document": ""},
]


def test_import_digests_are_deterministic_and_do_not_store_plain_payload(settings):
    settings.SECRET_KEY = "import-receipt-test-secret"

    first = import_batch_digest(domain="customers", headers=HEADERS, rows=ROWS)
    repeated = import_batch_digest(domain="customers", headers=HEADERS, rows=ROWS)
    row = import_row_digest(headers=HEADERS, row=ROWS[0])

    assert first == repeated
    assert len(first) == len(row) == 64
    assert "Cliente Sensível" not in first
    assert "52998224725" not in row
    assert first != import_batch_digest(domain="products", headers=HEADERS, rows=ROWS)


def test_completed_import_batch_is_idempotent_and_rows_are_technical_only(
    organization,
    other_organization,
    settings,
):
    settings.SECRET_KEY = "import-receipt-test-secret"
    digest = import_batch_digest(domain="customers", headers=HEADERS, rows=ROWS)

    batch, is_new = claim_import_batch(
        organization=organization,
        domain=DataImportBatchReceipt.Domain.CUSTOMERS,
        source_digest=digest,
        row_count=2,
    )
    assert is_new

    first_row = record_import_row(
        batch=batch,
        row_number=1,
        row_digest=import_row_digest(headers=HEADERS, row=ROWS[0]),
        entity_id="entity-1",
    )
    record_import_row(
        batch=batch,
        row_number=2,
        row_digest=import_row_digest(headers=HEADERS, row=ROWS[1]),
        entity_id="entity-2",
    )
    complete_import_batch(batch=batch)

    repeated, is_new = claim_import_batch(
        organization=organization,
        domain=DataImportBatchReceipt.Domain.CUSTOMERS,
        source_digest=digest,
        row_count=2,
    )
    other_batch, other_is_new = claim_import_batch(
        organization=other_organization,
        domain=DataImportBatchReceipt.Domain.CUSTOMERS,
        source_digest=digest,
        row_count=2,
    )

    assert repeated.id == batch.id
    assert not is_new
    assert other_is_new
    assert other_batch.organization == other_organization
    assert first_row.entity_id == "entity-1"
    persisted = str(
        list(
            batch.rows.values(
                "row_number",
                "row_digest",
                "entity_id",
            )
        )
    )
    assert "Cliente Sensível" not in persisted
    assert "52998224725" not in persisted


def test_import_receipts_reject_incomplete_or_inconsistent_batches(organization, settings):
    settings.SECRET_KEY = "import-receipt-test-secret"
    digest = import_batch_digest(domain="customers", headers=HEADERS, rows=ROWS)
    batch, _ = claim_import_batch(
        organization=organization,
        domain=DataImportBatchReceipt.Domain.CUSTOMERS,
        source_digest=digest,
        row_count=2,
    )

    with pytest.raises(ImportReceiptConflict, match="todas as linhas"):
        complete_import_batch(batch=batch)
    with pytest.raises(ImportReceiptConflict, match="processamento"):
        claim_import_batch(
            organization=organization,
            domain=DataImportBatchReceipt.Domain.CUSTOMERS,
            source_digest=digest,
            row_count=2,
        )
    with pytest.raises(ImportReceiptConflict, match="Domínio"):
        claim_import_batch(
            organization=organization,
            domain="invalid",
            source_digest="0" * 64,
            row_count=0,
        )
