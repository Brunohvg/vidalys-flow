import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.customers import transfer_views
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
    assert response["Content-Disposition"] == 'attachment; filename="clientes.csv"'
    assert "Cliente Visível" in content
    assert "Cliente Oculto" not in content


def test_customer_import_success_creates_contacts_and_can_be_exported(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    upload = _csv(
        "individual,Maria Importada,,,maria@example.com,11999999999,Cliente CSV",
        "company,Empresa Importada,Ltda,,,,Conta empresa",
    )

    response = client.post(reverse("customers:import-csv"), {"file": upload})

    assert response.status_code == 302
    maria = Customer.objects.get(organization=organization, display_name="Maria Importada")
    assert maria.contacts.filter(kind="email", normalized_value="maria@example.com").exists()
    assert maria.contacts.filter(kind="phone", normalized_value="+5511999999999").exists()
    assert Customer.objects.filter(organization=organization, display_name="Empresa Importada").exists()

    exported = client.get(reverse("customers:export-csv")).content.decode("utf-8-sig")
    assert "maria@example.com" not in exported
    assert "11999999999" not in exported
    assert "ma***@example.com" in exported
    assert "+55****99" in exported


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


def test_customer_import_rejects_missing_file_bad_header_and_row_limit(
    client,
    user,
    operator_membership,
    monkeypatch,
):
    client.force_login(user)
    missing = client.post(reverse("customers:import-csv"), {})
    assert missing.status_code == 200
    assert "Selecione um arquivo CSV" in missing.content.decode()

    bad_header = SimpleUploadedFile("clientes.csv", b"name\nMaria\n", content_type="text/csv")
    invalid = client.post(reverse("customers:import-csv"), {"file": bad_header})
    assert "Cabeçalho CSV inválido" in invalid.content.decode()

    monkeypatch.setattr(transfer_views, "MAX_IMPORT_ROWS", 1)
    too_many = client.post(
        reverse("customers:import-csv"),
        {"file": _csv("individual,A,,,,,", "individual,B,,,,,")},
    )
    assert "excede o limite de 1 linhas" in too_many.content.decode()


def test_customer_import_rejects_oversized_file(
    client,
    user,
    operator_membership,
    monkeypatch,
):
    client.force_login(user)
    monkeypatch.setattr(transfer_views, "MAX_IMPORT_BYTES", 16)
    response = client.post(
        reverse("customers:import-csv"),
        {"file": _csv("individual,Arquivo grande,,,,,")},
    )
    assert response.status_code == 200
    assert "excede o limite" in response.content.decode()


def test_customer_import_rejects_non_utf8_file(client, user, operator_membership):
    client.force_login(user)
    uploaded = SimpleUploadedFile("clientes.csv", b"\xff\xfe\xff", content_type="text/csv")
    response = client.post(reverse("customers:import-csv"), {"file": uploaded})
    assert response.status_code == 200
    assert "Importação cancelada" in response.content.decode()
