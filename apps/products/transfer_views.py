import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.organizations.selectors import active_organization_for_user
from apps.products import policies, selectors, services
from apps.products.exceptions import ProductDomainError

MAX_IMPORT_ROWS = 1000
PRODUCT_HEADERS = (
    "product_key",
    "product_name",
    "description",
    "default_unit",
    "variant_name",
    "sku",
    "barcode",
)


def _organization_or_redirect(request):
    organization, _ = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_products(user=request.user, organization=organization):
        return organization, None
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return None, redirect("organizations:list")


@login_required
def product_export_csv(request):
    organization, response = _organization_or_redirect(request)
    if response:
        return response
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="produtos.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(PRODUCT_HEADERS)
    products = selectors.products_for_organization(
        organization=organization,
        include_inactive=True,
    ).prefetch_related("variants")
    for product in products:
        variants = list(product.variants.all())
        if not variants:
            variants = [None]
        for variant in variants:
            writer.writerow(
                (
                    str(product.id),
                    product.name,
                    product.description,
                    product.default_unit,
                    variant.name if variant else "",
                    variant.sku if variant else "",
                    variant.barcode if variant else "",
                )
            )
    return response


@login_required
@require_http_methods(["GET", "POST"])
def product_import_csv(request):
    organization, response = _organization_or_redirect(request)
    if response:
        return response
    if not policies.can_manage_products(user=request.user, organization=organization):
        return redirect("products:list")

    if request.method == "POST":
        uploaded = request.FILES.get("file")
        if not uploaded:
            messages.error(request, "Selecione um arquivo CSV.")
        else:
            try:
                text = uploaded.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                if tuple(reader.fieldnames or ()) != PRODUCT_HEADERS:
                    raise ValueError("Cabeçalho CSV inválido.")
                rows = list(reader)
                if len(rows) > MAX_IMPORT_ROWS:
                    raise ValueError(f"O arquivo excede o limite de {MAX_IMPORT_ROWS} linhas.")
                groups = {}
                for index, row in enumerate(rows, start=2):
                    key = (row["product_key"] or "").strip()
                    name = (row["product_name"] or "").strip()
                    if not key:
                        raise ValueError(f"Linha {index}: product_key é obrigatório.")
                    if not name:
                        raise ValueError(f"Linha {index}: product_name é obrigatório.")
                    group = groups.setdefault(
                        key,
                        {
                            "name": name,
                            "description": row["description"],
                            "default_unit": row["default_unit"],
                            "variants": [],
                        },
                    )
                    if group["name"] != name:
                        raise ValueError(f"Linha {index}: product_key reutilizado com nome diferente.")
                    if any((row[field] or "").strip() for field in ("variant_name", "sku", "barcode")):
                        group["variants"].append(
                            {
                                "name": row["variant_name"],
                                "sku": row["sku"],
                                "barcode": row["barcode"],
                            }
                        )

                with transaction.atomic():
                    for group in groups.values():
                        product = services.create_product(
                            organization=organization,
                            actor=request.user,
                            name=group["name"],
                            description=group["description"],
                            default_unit=group["default_unit"],
                        )
                        for variant in group["variants"]:
                            services.create_variant(
                                organization=organization,
                                product=product,
                                actor=request.user,
                                **variant,
                            )
            except (UnicodeDecodeError, ValueError, ProductDomainError) as exc:
                messages.error(request, f"Importação cancelada: {exc}")
            else:
                messages.success(request, f"{len(groups)} produtos importados.")
                return redirect("products:list")

    return render(
        request,
        "products/import.html",
        {"organization": organization, "max_rows": MAX_IMPORT_ROWS, "headers": PRODUCT_HEADERS},
    )
