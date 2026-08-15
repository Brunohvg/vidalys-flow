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
from apps.organizations.selectors import active_organization_for_user

MAX_IMPORT_ROWS = 1000
CUSTOMER_HEADERS = ("customer_type", "display_name", "legal_name", "document", "email", "phone", "notes_summary")


def _organization_or_redirect(request):
    organization, _ = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_customers(user=request.user, organization=organization):
        return organization, None
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return None, redirect("organizations:list")


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
    organization, response = _organization_or_redirect(request)
    if response:
        return response
    rows = []
    for customer in selectors.customers_for_organization(organization=organization, include_inactive=True).prefetch_related(
        "contacts"
    ):
        email = customer.contacts.filter(kind="email", is_active=True).values_list("value", flat=True).first() or ""
        phone = (
            customer.contacts.filter(kind__in=("phone", "whatsapp"), is_active=True)
            .values_list("value", flat=True)
            .first()
            or ""
        )
        rows.append(
            (
                customer.customer_type,
                customer.display_name,
                customer.legal_name,
                customer.document_normalized,
                email,
                phone,
                customer.notes_summary,
            )
        )
    return _csv_response(filename="clientes.csv", rows=rows)


@login_required
@require_http_methods(["GET", "POST"])
def customer_import_csv(request):
    organization, response = _organization_or_redirect(request)
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
                with transaction.atomic():
                    for index, row in enumerate(rows, start=2):
                        customer_type = (row["customer_type"] or "").strip().lower()
                        if customer_type not in Customer.Type.values:
                            raise ValueError(f"Linha {index}: tipo de cliente inválido.")
                        if not (row["display_name"] or "").strip():
                            raise ValueError(f"Linha {index}: nome do cliente é obrigatório.")
                        services.create_customer(
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
            except (UnicodeDecodeError, ValueError, CustomerDomainError) as exc:
                messages.error(request, f"Importação cancelada: {exc}")
            else:
                messages.success(request, f"{len(rows)} clientes importados.")
                return redirect("customers:list")

    return render(
        request,
        "customers/import.html",
        {"organization": organization, "max_rows": MAX_IMPORT_ROWS, "headers": CUSTOMER_HEADERS},
    )
