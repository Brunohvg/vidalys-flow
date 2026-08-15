import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.customers.models import Customer
from apps.platform.models import DataImportBatchReceipt

pytestmark = pytest.mark.django_db


HEADER = "customer_type,display_name,legal_name,document,email,phone,notes_summary\n"
ROW = "individual,Cliente Sem Documento,,,retry@example.com,11999998888,Importado\n"


def _upload():
    return SimpleUploadedFile(
        "clientes.csv",
        (HEADER + ROW).encode("utf-8"),
        content_type="text/csv",
    )


def test_customer_csv_retry_is_noop_and_receipts_do_not_store_plain_customer_data(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)

    first = client.post(reverse("customers:import-csv"), {"file": _upload()})
    repeated = client.post(reverse("customers:import-csv"), {"file": _upload()})

    assert first.status_code == 302
    assert repeated.status_code == 302
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
