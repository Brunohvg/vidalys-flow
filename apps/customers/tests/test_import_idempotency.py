import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.customers.models import Customer
from apps.platform.models import DataImportBatchReceipt

pytestmark = pytest.mark.django_db


HEADERS = (
    "customer_type",
    "display_name",
    "legal_name",
    "document",
    "email",
    "phone",
    "notes_summary",
)
HEADER = ",".join(HEADERS) + "\n"
ROW = "individual,Cliente Sem Documento,,,retry@example.com,11999998888,Importado\n"


def _upload():
    return SimpleUploadedFile(
        "clientes.csv",
        (HEADER + ROW).encode("utf-8"),
        content_type="text/csv",
    )


def _confirmed_import(client):
    mapping = client.post(
        reverse("customers:import-csv"),
        {"step": "upload", "file": _upload()},
    )
    payload = {"step": "mapping", "stage": mapping.context["stage"]}
    payload.update({f"map_{header}": header for header in HEADERS})
    preview = client.post(reverse("customers:import-csv"), payload)
    return client.post(
        reverse("customers:import-csv"),
        {"step": "confirm", "stage": preview.context["stage"]},
    )


def test_customer_import_retry_is_noop_and_receipts_do_not_store_plain_customer_data(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)

    first = _confirmed_import(client)
    repeated = _confirmed_import(client)

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.context["already_imported"] is True
    assert Customer.objects.filter(
        organization=organization,
        display_name="Cliente Sem Documento",
    ).count() == 1

    batch = DataImportBatchReceipt.objects.get(
        organization=organization,
        domain=DataImportBatchReceipt.Domain.CUSTOMERS,
    )
    assert batch.completed
    assert batch.row_count == 1
    assert batch.rows.count() == 1

    persisted = str(
        {
            "source_digest": batch.source_digest,
            "rows": list(batch.rows.values("row_number", "row_digest", "entity_id")),
        }
    )
    assert "Cliente Sem Documento" not in persisted
    assert "retry@example.com" not in persisted
    assert "11999998888" not in persisted
