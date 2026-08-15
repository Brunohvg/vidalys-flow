import pytest
from django.urls import reverse

from apps.customers.models import Customer

pytestmark = pytest.mark.django_db


def test_customer_export_neutralizes_spreadsheet_formula(
    client,
    organization,
    user,
    operator_membership,
):
    Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="=2+2",
    )
    client.force_login(user)

    content = client.get(reverse("customers:export-csv")).content.decode("utf-8-sig")

    assert "'=2+2" in content
    assert ",=2+2," not in content
