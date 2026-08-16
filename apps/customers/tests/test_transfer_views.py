import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.customers import transfer_views
from apps.customers.models import Customer
from apps.platform.xlsx import build_xlsx, parse_xlsx

pytestmark = pytest.mark.django_db


HEADERS = (
    "customer_type",
    "display_name",
    "legal_name",
    "document",
    "email",
    "phone",
    "notes_summary",
)


def _csv(*rows):
    header = ",".join(HEADERS) + "\n"
    return SimpleUploadedFile(
        "clientes.csv",
        (header + "\n".join(rows) + "\n").encode(),
        content_type="text/csv",
    )


def _xlsx(*rows):
    payload = build_xlsx(headers=HEADERS, rows=rows)
    return SimpleUploadedFile(
        "clientes.xlsx",
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _preview(client, uploaded):
    uploaded_response = client.post(
        reverse("customers:import-csv"),
        {"step": "upload", "file": uploaded},
    )
    assert uploaded_response.status_code == 200
    assert uploaded_response.templates[0].name == "customers/import_mapping.html"
    mapping = {"step": "mapping", "stage": uploaded_response.context["stage"]}
    mapping.update({f"map_{header}": header for header in HEADERS})
    preview = client.post(reverse("customers:import-csv"), mapping)
    assert preview.status_code == 200
    assert preview.templates[0].name == "customers/import_preview.html"
    return preview


def _confirm(client, preview):
    return client.post(
        reverse("customers:import-csv"),
        {"step": "confirm", "stage": preview.context["stage"]},
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

    xlsx = client.get(reverse("customers:export-xlsx"))
    _, rows = parse_xlsx(xlsx.content, max_rows=10)
    assert any(row["display_name"] == "Cliente Visível" for row in rows)
    assert not any(row["display_name"] == "Cliente Oculto" for row in rows)


@pytest.mark.parametrize("file_kind", ["csv", "xlsx"])
def test_customer_import_requires_preview_before_atomic_confirmation(
    client,
    organization,
    user,
    operator_membership,
    file_kind,
):
    client.force_login(user)
    csv_row = "individual,Maria Importada,,,maria@example.com,11999999999,Cliente importada"
    xlsx_row = ("individual", "Maria Importada", "", "", "maria@example.com", "11999999999", "Cliente importada")
    uploaded = _csv(csv_row) if file_kind == "csv" else _xlsx(xlsx_row)

    preview = _preview(client, uploaded)

    assert preview.context["can_confirm"] is True
    assert not Customer.objects.filter(organization=organization, display_name="Maria Importada").exists()

    result = _confirm(client, preview)

    assert result.status_code == 200
    assert result.templates[0].name == "customers/import_result.html"
    maria = Customer.objects.get(organization=organization, display_name="Maria Importada")
    assert maria.contacts.filter(kind="email", normalized_value="maria@example.com").exists()
    assert maria.contacts.filter(kind="phone", normalized_value="+5511999999999").exists()


def test_customer_import_preview_blocks_invalid_row_without_writes(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    preview = _preview(
        client,
        _csv(
            "individual,Primeiro Cliente,,,,,",
            "invalid,Segundo Cliente,,,,,",
        ),
    )

    assert preview.context["can_confirm"] is False
    assert preview.context["errors"]
    assert not Customer.objects.filter(
        organization=organization,
        display_name__in=("Primeiro Cliente", "Segundo Cliente"),
    ).exists()


def test_customer_import_requires_mapping_for_required_fields(client, user, operator_membership):
    client.force_login(user)
    uploaded = SimpleUploadedFile("clientes.csv", b"name\nMaria\n", content_type="text/csv")
    mapping = client.post(reverse("customers:import-csv"), {"step": "upload", "file": uploaded})
    response = client.post(
        reverse("customers:import-csv"),
        {
            "step": "mapping",
            "stage": mapping.context["stage"],
            **{f"map_{header}": "__blank__" for header in HEADERS},
        },
    )
    assert response.status_code == 200
    assert "Mapeie o campo obrigatório" in response.content.decode()


def test_customer_import_rejects_missing_file_row_limit_and_oversized_file(
    client,
    user,
    operator_membership,
    monkeypatch,
):
    client.force_login(user)
    missing = client.post(reverse("customers:import-csv"), {"step": "upload"})
    assert "Selecione um arquivo CSV ou XLSX" in missing.content.decode()

    monkeypatch.setattr(transfer_views, "MAX_IMPORT_ROWS", 1)
    too_many = client.post(
        reverse("customers:import-csv"),
        {"step": "upload", "file": _csv("individual,A,,,,,", "individual,B,,,,,")},
    )
    assert "excede o limite de 1 linhas" in too_many.content.decode()

    monkeypatch.setattr(transfer_views, "MAX_IMPORT_BYTES", 16)
    oversized = client.post(
        reverse("customers:import-csv"),
        {"step": "upload", "file": _csv("individual,Arquivo grande,,,,,")},
    )
    assert "excede o limite" in oversized.content.decode()


def test_customer_import_rejects_non_utf8_csv(client, user, operator_membership):
    client.force_login(user)
    uploaded = SimpleUploadedFile("clientes.csv", b"\xff\xfe\xff", content_type="text/csv")
    response = client.post(reverse("customers:import-csv"), {"step": "upload", "file": uploaded})
    assert response.status_code == 200
    assert "CSV deve usar UTF-8" in response.content.decode()
