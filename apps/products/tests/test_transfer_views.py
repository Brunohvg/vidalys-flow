import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

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
    assert "Produto Visível" in content
    assert "Produto Oculto" not in content


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
