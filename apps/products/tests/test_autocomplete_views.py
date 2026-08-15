import pytest
from django.urls import reverse

from apps.products.models import Product

pytestmark = pytest.mark.django_db


def test_product_autocomplete_is_tenant_scoped(
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
    Product.objects.create(
        organization=other_organization,
        name="Caneca Oculta",
        default_unit="un",
    )
    client.force_login(user)

    response = client.get(reverse("products:autocomplete"), {"q": "Caneca"})

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"id": str(visible.id), "label": "Caneca Visível", "unit": "un"}]
    }
