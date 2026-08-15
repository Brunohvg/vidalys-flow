import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.customers import policies, selectors, services
from apps.customers.exceptions import CustomerDomainError
from apps.customers.models import Customer
from apps.customers.normalization import mask_contact, mask_document, normalize_document
from apps.organizations.selectors import active_organization_for_user
from apps.platform.csv_safety import spreadsheet_safe_cell
from apps.platform.import_receipts import (
    ImportReceiptConflict,
    claim_import_batch,
    complete_import_batch,
    import_batch_digest,
    import_row_digest,
    record_import_row,
)
from apps.platform.models import DataImportBatchReceipt
from apps.platform.tabular_import import (
    BLANK_MAPPING,
    TabularImportError,
    apply_mapping,
    dump_stage,
    load_stage,
    mapping_from_post,
    parse_uploaded_table,
    suggested_mapping,
)
from apps.platform.xlsx import build_xlsx

MAX_IMPORT_ROWS = 1000
MAX_IMPORT_BYTES = 2 * 1024 * 1024
CUSTOMER_HEADERS = (
    "customer_type",
    "display_name",
    "legal_name",
    "document",
    "email",
    "phone",
    "notes_summary",
)
REQUIRED_CUSTOMER_HEADERS = ("customer_type", "display_name")


def _organization_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_customers(user=request.user, organization=organization):
        return organization, membership, None
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return None, None, redirect("organizations:list")


def _customer_export_rows(*, organization, membership):
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
    return rows


@login_required
def customer_export_csv(request):
    organization, membership, response = _organization_or_redirect(request)
    if response:
        return response
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="clientes.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(CUSTOMER_HEADERS)
    writer.writerows(
        tuple(spreadsheet_safe_cell(value) for value in row)
        for row in _customer_export_rows(organization=organization, membership=membership)
    )
    return response


@login_required
def customer_export_xlsx(request):
    organization, membership, response = _organization_or_redirect(request)
    if response:
        return response
    payload = build_xlsx(
        headers=CUSTOMER_HEADERS,
        rows=_customer_export_rows(organization=organization, membership=membership),
    )
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="clientes.xlsx"'
    return response


def _validate_customer_rows(*, organization, rows):
    errors = []
    conflicts = []
    documents = {}
    for index, row in enumerate(rows, start=2):
        customer_type = (row["customer_type"] or "").strip().lower()
        display_name = (row["display_name"] or "").strip()
        if customer_type not in Customer.Type.values:
            errors.append(f"Linha {index}: tipo de cliente inválido.")
        if not display_name:
            errors.append(f"Linha {index}: nome do cliente é obrigatório.")
        raw_document = (row["document"] or "").strip()
        if raw_document:
            try:
                document = normalize_document(raw_document)
            except ValueError as exc:
                errors.append(f"Linha {index}: {exc}")
            else:
                if customer_type == Customer.Type.INDIVIDUAL and len(document) != 11:
                    errors.append(f"Linha {index}: pessoa física deve usar CPF.")
                elif customer_type == Customer.Type.COMPANY and len(document) != 14:
                    errors.append(f"Linha {index}: pessoa jurídica deve usar CNPJ.")
                elif document in documents:
                    conflicts.append(
                        f"Linha {index}: documento repetido no arquivo (também na linha {documents[document]})."
                    )
                else:
                    documents[document] = index
                    if selectors.find_by_document(
                        organization=organization,
                        document_normalized=document,
                    ):
                        conflicts.append(f"Linha {index}: documento já cadastrado nesta Organization.")
    return errors, conflicts


def _masked_preview_rows(*, rows, membership):
    if membership.role in policies.MANAGER_ROLES:
        return rows[:20]
    preview = []
    for row in rows[:20]:
        masked = dict(row)
        masked["document"] = mask_document((row["document"] or "").replace(".", "").replace("-", "").replace("/", ""))
        if row["email"]:
            masked["email"] = mask_contact("email", row["email"])
        if row["phone"]:
            masked["phone"] = mask_contact("phone", row["phone"])
        preview.append(masked)
    return preview


def _render_upload(request, *, organization):
    return render(
        request,
        "customers/import.html",
        {
            "organization": organization,
            "max_rows": MAX_IMPORT_ROWS,
            "headers": CUSTOMER_HEADERS,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def customer_import_csv(request):
    organization, membership, response = _organization_or_redirect(request)
    if response:
        return response
    if not policies.can_manage_customers(user=request.user, organization=organization):
        return redirect("customers:list")
    if request.method == "GET":
        return _render_upload(request, organization=organization)

    step = request.POST.get("step", "upload")
    try:
        if step == "upload":
            uploaded = request.FILES.get("file")
            if not uploaded:
                raise TabularImportError("Selecione um arquivo CSV ou XLSX.")
            source_headers, source_rows = parse_uploaded_table(
                uploaded=uploaded,
                max_bytes=MAX_IMPORT_BYTES,
                max_rows=MAX_IMPORT_ROWS,
            )
            return render(
                request,
                "customers/import_mapping.html",
                {
                    "organization": organization,
                    "canonical_headers": CUSTOMER_HEADERS,
                    "required_headers": REQUIRED_CUSTOMER_HEADERS,
                    "source_headers": source_headers,
                    "blank_mapping": BLANK_MAPPING,
                    "suggested_mapping": suggested_mapping(
                        canonical_headers=CUSTOMER_HEADERS,
                        source_headers=source_headers,
                    ),
                    "stage": dump_stage(headers=source_headers, rows=source_rows),
                },
            )

        if step == "mapping":
            source_headers, source_rows = load_stage(request.POST.get("stage", ""))
            mapping = mapping_from_post(
                canonical_headers=CUSTOMER_HEADERS,
                source_headers=source_headers,
                post=request.POST,
            )
            for required in REQUIRED_CUSTOMER_HEADERS:
                if mapping[required] == BLANK_MAPPING:
                    raise TabularImportError(f"Mapeie o campo obrigatório {required}.")
            rows = apply_mapping(
                canonical_headers=CUSTOMER_HEADERS,
                rows=source_rows,
                mapping=mapping,
            )
            errors, conflicts = _validate_customer_rows(organization=organization, rows=rows)
            return render(
                request,
                "customers/import_preview.html",
                {
                    "organization": organization,
                    "headers": CUSTOMER_HEADERS,
                    "rows": _masked_preview_rows(rows=rows, membership=membership),
                    "row_count": len(rows),
                    "errors": errors,
                    "conflicts": conflicts,
                    "can_confirm": not errors and not conflicts,
                    "stage": dump_stage(headers=CUSTOMER_HEADERS, rows=rows),
                },
            )

        if step != "confirm":
            raise TabularImportError("Etapa de importação inválida.")
        stage_headers, rows = load_stage(request.POST.get("stage", ""))
        if stage_headers != CUSTOMER_HEADERS:
            raise TabularImportError("Prévia canônica inválida.")
        errors, conflicts = _validate_customer_rows(organization=organization, rows=rows)
        if errors or conflicts:
            raise TabularImportError("A prévia ficou obsoleta; revise validações e conflitos novamente.")

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
                return render(
                    request,
                    "customers/import_result.html",
                    {"organization": organization, "count": len(rows), "already_imported": True},
                )
            for index, row in enumerate(rows, start=2):
                customer = services.create_customer(
                    organization=organization,
                    actor=request.user,
                    customer_type=(row["customer_type"] or "").strip().lower(),
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
        return render(
            request,
            "customers/import_result.html",
            {"organization": organization, "count": len(rows), "already_imported": False},
        )
    except (TabularImportError, CustomerDomainError, ImportReceiptConflict) as exc:
        messages.error(request, f"Importação cancelada: {exc}")
        return _render_upload(request, organization=organization)
