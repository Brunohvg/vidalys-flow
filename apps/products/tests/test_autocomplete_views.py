import pytest
from django.urls import reverse

from apps.products.models import Product, ProductVariant

pytestmark = pytest.mark.django_db


def test_product_autocomplete_is_organization_scoped(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    visible = Product.objects.create(
        organization=organization,
        name="Caneca Visível",
        default_unit="un",
    )
    hidden = Product.objects.create(
        organization=other_organization,
        name="Caneca Oculta",
        default_unit="un",
    )
    ProductVariant.objects.create(
        organization=organization,
        product=visible,
        name="Azul",
        sku="CAN-AZ",
        barcode="789001",
    )
    ProductVariant.objects.create(
        organization=other_organization,
        product=hidden,
        name="Oculta",
        sku="CAN-OC",
        barcode="789999",
    )
    client.force_login(user)

    response = client.get(reverse("products:autocomplete"), {"q": "Caneca"})

    assert response.status_code == 200
    results = response.json()["results"]
    assert any(item["product_id"] == str(visible.id) for item in results)
    assert not any(item["product_id"] == str(hidden.id) for item in results)


def test_product_autocomplete_returns_exact_variant_for_sku_and_barcode(
    client,
    organization,
    user,
    operator_membership,
):
    product = Product.objects.create(
        organization=organization,
        name="Fita Cetim",
        default_unit="un",
    )
    variant = ProductVariant.objects.create(
        organization=organization,
        product=product,
        name="Rosa",
        sku="FIT-ROSA-38",
        barcode="7891234567890",
    )
    client.force_login(user)

    by_sku = client.get(reverse("products:autocomplete"), {"q": "FIT-ROSA"}).json()["results"]
    by_barcode = client.get(reverse("products:autocomplete"), {"q": "789123"}).json()["results"]

    for results in (by_sku, by_barcode):
        exact = next(item for item in results if item["kind"] == "variant")
        assert exact["variant_id"] == str(variant.id)
        assert exact["product_id"] == str(product.id)
        assert "FIT-ROSA-38" in exact["label"]
