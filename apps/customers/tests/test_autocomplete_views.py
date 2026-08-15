import pytest
from django.urls import reverse

from apps.customers.models import Customer

pytestmark = pytest.mark.django_db


def test_customer_autocomplete_is_tenant_scoped_and_pii_minimal(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    visible = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Maria Visível",
        document_normalized="52998224725",
    )
    Customer.objects.create(
        organization=other_organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Maria Oculta",
    )
    client.force_login(user)

    response = client.get(reverse("customers:autocomplete"), {"q": "Maria"})
    payload = response.json()

    assert response.status_code == 200
    assert payload == {"results": [{"id": str(visible.id), "label": "Maria Visível"}]}
    assert "52998224725" not in response.content.decode()
