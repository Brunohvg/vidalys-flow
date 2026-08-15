import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.customers.models import Customer

pytestmark = pytest.mark.django_db


def _csv(*rows):
    header = "customer_type,display_name,legal_name,document,email,phone,notes_summary\n"
    return SimpleUploadedFile(
        "clientes.csv",
        (header + "\n".join(rows) + "\n").encode(),
        content_type="text/csv",
    )


def test_customer_export_does_not_leak_other_organization(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente Visível",
    )
    Customer.objects.create(
        organization=other_organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente Oculto",
    )
    client.force_login(user)

    response = client.get(reverse("customers:export-csv"))
    content = response.content.decode("utf-8-sig")

    assert response.status_code == 200
    assert "Cliente Visível" in content
    assert "Cliente Oculto" not in content


def test_customer_import_rolls_back_entire_file_on_invalid_row(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    upload = _csv(
        "individual,Primeiro Cliente,,,,,",
        "invalid,Segundo Cliente,,,,,",
    )

    response = client.post(reverse("customers:import-csv"), {"file": upload})

    assert response.status_code == 200
    assert not Customer.objects.filter(
        organization=organization,
        display_name__in=("Primeiro Cliente", "Segundo Cliente"),
    ).exists()
    assert "Importação cancelada" in response.content.decode()
