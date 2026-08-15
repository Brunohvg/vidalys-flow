import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.customers import policies, selectors, services
from apps.customers.exceptions import CustomerDomainError
from apps.customers.models import Customer
from apps.customers.normalization import mask_contact, mask_document
from apps.organizations.selectors import active_organization_for_user
from apps.platform.import_receipts import (
    ImportReceiptConflict,
    claim_import_batch,
    complete_import_batch,
    import_batch_digest,
    import_row_digest,
    record_import_row,
)
from apps.platform.models import DataImportBatchReceipt

MAX_IMPORT_ROWS = 1000
CUSTOMER_HEADERS = (
    "customer_type",
    "display_name",
    "legal_name",
    "document",
    "email",
    "phone",
    "notes_summary",
)


def _organization_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_customers(user=request.user, organization=organization):
        return organization, membership, None
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return None, None, redirect("organizations:list")


def _csv_response(*, filename, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(CUSTOMER_HEADERS)
    writer.writerows(rows)
    return response


@login_required
def customer_export_csv(request):
    organization, membership, response = _organization_or_redirect(request)
    if response:
        return response
    full_access = membership.role in policies.MANAGER_ROLES
    rows = []
    customers = selectors.customers_for_organization(
        organization=organization,
        include_inactive=True,
    ).prefetch_related("contacts")
    for customer in customers:
        email_contact = customer.contacts.filter(kind="email", is_active=True).first()
        phone_contact = customer.contacts.filter(kind__in=("phone", "whatsapp"), is_active=True).first()
        document = customer.document_normalized if full_access else mask_document(customer.document_normalized)
        email = ""
        phone = ""
        if email_contact:
            email = (
                email_contact.value
                if full_access
                else mask_contact(email_contact.kind, email_contact.normalized_value)
            )
        if phone_contact:
            phone = (
                phone_contact.value
                if full_access
                else mask_contact(phone_contact.kind, phone_contact.normalized_value)
            )
        rows.append(
            (
                customer.customer_type,
                customer.display_name,
                customer.legal_name,
                document,
                email,
                phone,
                customer.notes_summary,
            )
        )
    return _csv_response(filename="clientes.csv", rows=rows)


@login_required
@require_http_methods(["GET", "POST"])
def customer_import_csv(request):
    organization, _membership, response = _organization_or_redirect(request)
    if response:
        return response
    if not policies.can_manage_customers(user=request.user, organization=organization):
        return redirect("customers:list")

    if request.method == "POST":
        uploaded = request.FILES.get("file")
        if not uploaded:
            messages.error(request, "Selecione um arquivo CSV.")
        else:
            try:
                text = uploaded.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                if tuple(reader.fieldnames or ()) != CUSTOMER_HEADERS:
                    raise ValueError("Cabeçalho CSV inválido.")
                rows = list(reader)
                if len(rows) > MAX_IMPORT_ROWS:
                    raise ValueError(f"O arquivo excede o limite de {MAX_IMPORT_ROWS} linhas.")
                source_digest = import_batch_digest(
                    domain=DataImportBatchReceipt.Domain.CUSTOMERS,
                    headers=CUSTOMER_HEADERS,
                    rows=rows,
                )
                with transaction.atomic():
                    batch, is_new = claim_import_batch(
                        organization=organization,
                        domain=DataImportBatchReceipt.Domain.CUSTOMERS,
                        source_digest=source_digest,
                        row_count=len(rows),
                    )
                    if not is_new:
                        messages.info(request, "Este arquivo de clientes já foi importado.")
                        return redirect("customers:list")
                    for index, row in enumerate(rows, start=2):
                        customer_type = (row["customer_type"] or "").strip().lower()
                        if customer_type not in Customer.Type.values:
                            raise ValueError(f"Linha {index}: tipo de cliente inválido.")
                        if not (row["display_name"] or "").strip():
                            raise ValueError(f"Linha {index}: nome do cliente é obrigatório.")
                        customer = services.create_customer(
                            organization=organization,
                            actor=request.user,
                            customer_type=customer_type,
                            display_name=row["display_name"],
                            legal_name=row["legal_name"],
                            document=row["document"],
                            email=row["email"],
                            phone=row["phone"],
                            notes_summary=row["notes_summary"],
                        )
                        record_import_row(
                            batch=batch,
                            row_number=index,
                            row_digest=import_row_digest(headers=CUSTOMER_HEADERS, row=row),
                            entity_id=customer.id,
                        )
                    complete_import_batch(batch=batch)
            except (
                UnicodeDecodeError,
                ValueError,
                CustomerDomainError,
                ImportReceiptConflict,
            ) as exc:
                messages.error(request, f"Importação cancelada: {exc}")
            else:
                messages.success(request, f"{len(rows)} clientes importados.")
                return redirect("customers:list")

    return render(
        request,
        "customers/import.html",
        {"organization": organization, "max_rows": MAX_IMPORT_ROWS, "headers": CUSTOMER_HEADERS},
    )
