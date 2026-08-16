import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.products import transfer_views
from apps.products.models import Product
from apps.platform.xlsx import build_xlsx, parse_xlsx

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


def _csv(*rows):
    return SimpleUploadedFile(
        "produtos.csv",
        ((",".join(HEADERS) + "\n") + "\n".join(rows) + "\n").encode(),
        content_type="text/csv",
    )


def _xlsx(*rows):
    return SimpleUploadedFile(
        "produtos.xlsx",
        build_xlsx(headers=HEADERS, rows=rows),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _preview(client, uploaded):
    mapping = client.post(
        reverse("products:import-csv"),
        {"step": "upload", "file": uploaded},
    )
    assert mapping.status_code == 200
    assert mapping.templates[0].name == "products/import_mapping.html"
    payload = {"step": "mapping", "stage": mapping.context["stage"]}
    payload.update({f"map_{header}": header for header in HEADERS})
    preview = client.post(reverse("products:import-csv"), payload)
    assert preview.status_code == 200
    assert preview.templates[0].name == "products/import_preview.html"
    return preview


def _confirm(client, preview):
    return client.post(
        reverse("products:import-csv"),
        {"step": "confirm", "stage": preview.context["stage"]},
    )


def test_product_export_does_not_leak_other_organization(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    Product.objects.create(organization=organization, name="Produto Visível", default_unit="un")
    Product.objects.create(organization=other_organization, name="Produto Oculto", default_unit="un")
    client.force_login(user)

    response = client.get(reverse("products:export-csv"))
    content = response.content.decode("utf-8-sig")

    assert response.status_code == 200
    assert "Produto Visível" in content
    assert "Produto Oculto" not in content

    xlsx = client.get(reverse("products:export-xlsx"))
    _, rows = parse_xlsx(xlsx.content, max_rows=10)
    assert any(row["product_name"] == "Produto Visível" for row in rows)
    assert not any(row["product_name"] == "Produto Oculto" for row in rows)


@pytest.mark.parametrize("file_kind", ["csv", "xlsx"])
def test_product_import_groups_variants_only_after_confirmation(
    client,
    organization,
    user,
    operator_membership,
    file_kind,
):
    client.force_login(user)
    csv_rows = (
        "caneca,Caneca Premium,Caneca da loja,un,Branca,CAN-BR,789001",
        "caneca,Caneca Premium,Caneca da loja,un,Preta,CAN-PT,789002",
        "adesivo,Adesivo,,un,,,,",
    )
    xlsx_rows = (
        ("caneca", "Caneca Premium", "Caneca da loja", "un", "Branca", "CAN-BR", "789001"),
        ("caneca", "Caneca Premium", "Caneca da loja", "un", "Preta", "CAN-PT", "789002"),
        ("adesivo", "Adesivo", "", "un", "", "", ""),
    )
    preview = _preview(client, _csv(*csv_rows) if file_kind == "csv" else _xlsx(*xlsx_rows))

    assert preview.context["can_confirm"] is True
    assert not Product.objects.filter(organization=organization, name="Caneca Premium").exists()

    result = _confirm(client, preview)

    assert result.status_code == 200
    caneca = Product.objects.get(organization=organization, name="Caneca Premium")
    assert list(caneca.variants.order_by("sku").values_list("sku", flat=True)) == ["CAN-BR", "CAN-PT"]
    assert Product.objects.filter(organization=organization, name="Adesivo").exists()


def test_product_import_preview_blocks_duplicate_sku_without_writes(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    preview = _preview(
        client,
        _csv(
            "produto-a,Produto A,,un,Variação A,SKU-IGUAL,",
            "produto-b,Produto B,,un,Variação B,SKU-IGUAL,",
        ),
    )

    assert preview.context["can_confirm"] is False
    assert preview.context["conflicts"]
    assert not Product.objects.filter(
        organization=organization,
        name__in=("Produto A", "Produto B"),
    ).exists()


def test_product_import_preview_detects_inconsistent_key(client, user, operator_membership):
    client.force_login(user)
    preview = _preview(
        client,
        _csv("same,Produto A,,un,,,,", "same,Produto B,,un,,,,"),
    )
    assert preview.context["can_confirm"] is False
    assert any("product_key reutilizado" in error for error in preview.context["errors"])


def test_product_import_rejects_missing_file_row_limit_and_oversized_file(
    client,
    user,
    operator_membership,
    monkeypatch,
):
    client.force_login(user)
    missing = client.post(reverse("products:import-csv"), {"step": "upload"})
    assert "Selecione um arquivo CSV ou XLSX" in missing.content.decode()

    monkeypatch.setattr(transfer_views, "MAX_IMPORT_ROWS", 1)
    too_many = client.post(
        reverse("products:import-csv"),
        {"step": "upload", "file": _csv("a,A,,un,,,,", "b,B,,un,,,,")},
    )
    assert "excede o limite de 1 linhas" in too_many.content.decode()

    monkeypatch.setattr(transfer_views, "MAX_IMPORT_BYTES", 16)
    oversized = client.post(
        reverse("products:import-csv"),
        {"step": "upload", "file": _csv("p,Arquivo grande,,un,,,,")},
    )
    assert "excede o limite" in oversized.content.decode()


def test_product_import_requires_required_mapping(client, user, operator_membership):
    client.force_login(user)
    uploaded = SimpleUploadedFile("produtos.csv", b"name\nProduto\n", content_type="text/csv")
    mapping = client.post(reverse("products:import-csv"), {"step": "upload", "file": uploaded})
    response = client.post(
        reverse("products:import-csv"),
        {
            "step": "mapping",
            "stage": mapping.context["stage"],
            **{f"map_{header}": "__blank__" for header in HEADERS},
        },
    )
    assert "Mapeie o campo obrigatório" in response.content.decode()


def test_product_import_rejects_non_utf8_csv(client, user, operator_membership):
    client.force_login(user)
    binary = SimpleUploadedFile("produtos.csv", b"\xff\xfe\xff", content_type="text/csv")
    response = client.post(reverse("products:import-csv"), {"step": "upload", "file": binary})
    assert "CSV deve usar UTF-8" in response.content.decode()
