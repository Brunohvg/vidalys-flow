import pytest
from django.urls import reverse

from apps.products.models import Product

pytestmark = pytest.mark.django_db


def test_product_export_neutralizes_spreadsheet_formula(
    client,
    organization,
    user,
    operator_membership,
):
    Product.objects.create(
        organization=organization,
        name="=2+2",
        default_unit="un",
    )
    client.force_login(user)

    content = client.get(reverse("products:export-csv")).content.decode("utf-8-sig")

    assert "'=2+2" in content
    assert ",=2+2," not in content
