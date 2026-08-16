import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.platform.models import DataImportBatchReceipt
from apps.products.models import Product

pytestmark = pytest.mark.django_db


HEADERS = (
    "product_key",
    "product_name",
    "description",
    "default_unit",
    "variant_name",
    "sku",
    "barcode",
)
HEADER = ",".join(HEADERS) + "\n"
ROWS = (
    "produto-sem-sku,Produto Sem SKU,Descrição segura,un,,,,\n"
    "produto-com-variantes,Produto Com Variantes,,un,Branca,SKU-BR,789001\n"
    "produto-com-variantes,Produto Com Variantes,,un,Preta,SKU-PT,789002\n"
)


def _upload():
    return SimpleUploadedFile(
        "produtos.csv",
        (HEADER + ROWS).encode("utf-8"),
        content_type="text/csv",
    )


def _confirmed_import(client):
    mapping = client.post(
        reverse("products:import-csv"),
        {"step": "upload", "file": _upload()},
    )
    payload = {"step": "mapping", "stage": mapping.context["stage"]}
    payload.update({f"map_{header}": header for header in HEADERS})
    preview = client.post(reverse("products:import-csv"), payload)
    return client.post(
        reverse("products:import-csv"),
        {"step": "confirm", "stage": preview.context["stage"]},
    )


def test_product_import_retry_is_noop_and_preserves_grouped_variants(
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
    assert Product.objects.filter(
        organization=organization,
        name="Produto Sem SKU",
    ).count() == 1
    grouped = Product.objects.get(
        organization=organization,
        name="Produto Com Variantes",
    )
    assert list(grouped.variants.order_by("sku").values_list("sku", flat=True)) == [
        "SKU-BR",
        "SKU-PT",
    ]

    batch = DataImportBatchReceipt.objects.get(
        organization=organization,
        domain=DataImportBatchReceipt.Domain.PRODUCTS,
    )
    assert batch.completed
    assert batch.row_count == 3
    assert batch.rows.count() == 3

    persisted = str(
        {
            "source_digest": batch.source_digest,
            "rows": list(batch.rows.values("row_number", "row_digest", "entity_id")),
        }
    )
    assert "Produto Sem SKU" not in persisted
    assert "Produto Com Variantes" not in persisted
    assert "SKU-BR" not in persisted
    assert "789001" not in persisted
