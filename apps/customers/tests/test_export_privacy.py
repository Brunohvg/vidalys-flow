import pytest
from django.urls import reverse

from apps.customers.models import ContactPoint, Customer

pytestmark = pytest.mark.django_db


def _customer_with_pii(*, organization, name="Cliente Privado"):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name=name,
        document_normalized="52998224725",
    )
    ContactPoint.objects.create(
        customer=customer,
        kind=ContactPoint.Kind.EMAIL,
        value="maria@example.com",
        normalized_value="maria@example.com",
        is_primary=True,
    )
    ContactPoint.objects.create(
        customer=customer,
        kind=ContactPoint.Kind.PHONE,
        value="11999999999",
        normalized_value="+5511999999999",
        is_primary=True,
    )
    return customer


def test_operator_export_masks_customer_pii(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    _customer_with_pii(organization=organization)
    hidden = _customer_with_pii(organization=other_organization, name="Cliente Oculto")
    hidden.document_normalized = "11144477735"
    hidden.save(update_fields=("document_normalized", "updated_at"))
    client.force_login(user)

    response = client.get(reverse("customers:export-csv"))
    content = response.content.decode("utf-8-sig")

    assert response.status_code == 200
    assert "52998224725" not in content
    assert "maria@example.com" not in content
    assert "+5511999999999" not in content
    assert "*******4725" in content
    assert "ma***@example.com" in content
    assert "+55****99" in content
    assert "Cliente Oculto" not in content
    assert "11144477735" not in content


def test_manager_export_keeps_full_customer_pii(
    client,
    organization,
    manager,
    manager_membership,
):
    _customer_with_pii(organization=organization)
    client.force_login(manager)

    response = client.get(reverse("customers:export-csv"))
    content = response.content.decode("utf-8-sig")

    assert response.status_code == 200
    assert "52998224725" in content
    assert "maria@example.com" in content
    assert "11999999999" in content
