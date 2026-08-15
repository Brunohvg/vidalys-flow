import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.products import transfer_views
from apps.products.models import Product

pytestmark = pytest.mark.django_db


def _csv(*rows):
    header = "product_key,product_name,description,default_unit,variant_name,sku,barcode\n"
    return SimpleUploadedFile(
        "produtos.csv",
        (header + "\n".join(rows) + "\n").encode(),
        content_type="text/csv",
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
    assert response["Content-Disposition"] == 'attachment; filename="produtos.csv"'
    assert "Produto Visível" in content
    assert "Produto Oculto" not in content


def test_product_import_success_groups_variants_and_exports_them(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    upload = _csv(
        "caneca,Caneca Premium,Caneca da loja,un,Branca,CAN-BR,789001",
        "caneca,Caneca Premium,Caneca da loja,un,Preta,CAN-PT,789002",
        "adesivo,Adesivo,,un,,,,",
    )

    response = client.post(reverse("products:import-csv"), {"file": upload})

    assert response.status_code == 302
    caneca = Product.objects.get(organization=organization, name="Caneca Premium")
    assert list(caneca.variants.order_by("sku").values_list("sku", flat=True)) == ["CAN-BR", "CAN-PT"]
    assert Product.objects.filter(organization=organization, name="Adesivo").exists()

    exported = client.get(reverse("products:export-csv")).content.decode("utf-8-sig")
    assert "CAN-BR" in exported
    assert "CAN-PT" in exported
    assert "Adesivo" in exported


def test_product_import_rolls_back_entire_file_on_duplicate_sku(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    upload = _csv(
        "produto-a,Produto A,,un,Variação A,SKU-IGUAL,",
        "produto-b,Produto B,,un,Variação B,SKU-IGUAL,",
    )

    response = client.post(reverse("products:import-csv"), {"file": upload})

    assert response.status_code == 200
    assert not Product.objects.filter(
        organization=organization,
        name__in=("Produto A", "Produto B"),
    ).exists()
    assert "Importação cancelada" in response.content.decode()


def test_product_import_rejects_missing_file_header_limit_and_inconsistent_key(
    client,
    user,
    operator_membership,
    monkeypatch,
):
    client.force_login(user)
    missing = client.post(reverse("products:import-csv"), {})
    assert "Selecione um arquivo CSV" in missing.content.decode()

    bad_header = SimpleUploadedFile("produtos.csv", b"name\nProduto\n", content_type="text/csv")
    invalid = client.post(reverse("products:import-csv"), {"file": bad_header})
    assert "Cabeçalho CSV inválido" in invalid.content.decode()

    inconsistent = client.post(
        reverse("products:import-csv"),
        {"file": _csv("same,Produto A,,un,,,,", "same,Produto B,,un,,,,")},
    )
    assert "product_key reutilizado com nome diferente" in inconsistent.content.decode()

    monkeypatch.setattr(transfer_views, "MAX_IMPORT_ROWS", 1)
    too_many = client.post(
        reverse("products:import-csv"),
        {"file": _csv("a,A,,un,,,,", "b,B,,un,,,,")},
    )
    assert "excede o limite de 1 linhas" in too_many.content.decode()


def test_product_import_rejects_missing_key_name_and_non_utf8(
    client,
    user,
    operator_membership,
):
    client.force_login(user)
    missing_key = client.post(reverse("products:import-csv"), {"file": _csv(",Produto,,un,,,,")})
    assert "product_key é obrigatório" in missing_key.content.decode()

    missing_name = client.post(reverse("products:import-csv"), {"file": _csv("p,,,un,,,,")})
    assert "product_name é obrigatório" in missing_name.content.decode()

    binary = SimpleUploadedFile("produtos.csv", b"\xff\xfe\xff", content_type="text/csv")
    invalid_encoding = client.post(reverse("products:import-csv"), {"file": binary})
    assert "Importação cancelada" in invalid_encoding.content.decode()
