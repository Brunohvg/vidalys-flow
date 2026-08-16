import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

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
)
from apps.platform.xlsx import build_xlsx
from apps.products import policies, selectors, services
from apps.products.exceptions import ProductDomainError
from apps.products.models import ProductVariant
from apps.products.normalization import normalize_barcode, normalize_sku

MAX_IMPORT_ROWS = 1000
MAX_IMPORT_BYTES = 2 * 1024 * 1024
PRODUCT_HEADERS = (
    "product_key",
    "product_name",
    "description",
    "default_unit",
    "variant_name",
    "sku",
    "barcode",
)
REQUIRED_PRODUCT_HEADERS = ("product_key", "product_name")


def _organization_or_redirect(request):
    organization, _ = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_products(user=request.user, organization=organization):
        return organization, None
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return None, redirect("organizations:list")


def _product_export_rows(*, organization):
    rows = []
    products = selectors.products_for_organization(
        organization=organization,
        include_inactive=True,
    ).prefetch_related("variants")
    for product in products:
        variants = list(product.variants.all()) or [None]
        for variant in variants:
            rows.append(
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
    return rows


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
    writer.writerows(
        tuple(spreadsheet_safe_cell(value) for value in row)
        for row in _product_export_rows(organization=organization)
    )
    return response


@login_required
def product_export_xlsx(request):
    organization, response = _organization_or_redirect(request)
    if response:
        return response
    payload = build_xlsx(
        headers=PRODUCT_HEADERS,
        rows=_product_export_rows(organization=organization),
    )
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="produtos.xlsx"'
    return response


def _group_product_rows(rows):
    groups = {}
    errors = []
    for index, row in enumerate(rows, start=2):
        key = (row["product_key"] or "").strip()
        name = (row["product_name"] or "").strip()
        if not key:
            errors.append(f"Linha {index}: product_key é obrigatório.")
            continue
        if not name:
            errors.append(f"Linha {index}: product_name é obrigatório.")
            continue
        group = groups.setdefault(
            key,
            {
                "name": name,
                "description": row["description"],
                "default_unit": row["default_unit"],
                "entries": [],
            },
        )
        if group["name"] != name:
            errors.append(f"Linha {index}: product_key reutilizado com nome diferente.")
        group["entries"].append({"row_number": index, "row": row})
    return groups, errors


def _validate_product_rows(*, organization, rows):
    groups, errors = _group_product_rows(rows)
    conflicts = []
    seen_skus = {}
    seen_barcodes = {}
    for index, row in enumerate(rows, start=2):
        raw_sku = (row["sku"] or "").strip()
        raw_barcode = (row["barcode"] or "").strip()
        try:
            sku = normalize_sku(raw_sku)
            barcode = normalize_barcode(raw_barcode)
        except ValueError as exc:
            errors.append(f"Linha {index}: {exc}")
            continue
        if sku:
            key = sku.lower()
            if key in seen_skus:
                conflicts.append(f"Linha {index}: SKU repetido no arquivo (linha {seen_skus[key]}).")
            else:
                seen_skus[key] = index
                if ProductVariant.objects.filter(organization=organization, sku__iexact=sku).exists():
                    conflicts.append(f"Linha {index}: SKU já cadastrado nesta Organization.")
        if barcode:
            if barcode in seen_barcodes:
                conflicts.append(
                    f"Linha {index}: código de barras repetido no arquivo (linha {seen_barcodes[barcode]})."
                )
            else:
                seen_barcodes[barcode] = index
                if ProductVariant.objects.filter(organization=organization, barcode=barcode).exists():
                    conflicts.append(f"Linha {index}: código de barras já cadastrado nesta Organization.")
    return groups, errors, conflicts


def _render_upload(request, *, organization):
    return render(
        request,
        "products/import.html",
        {
            "organization": organization,
            "max_rows": MAX_IMPORT_ROWS,
            "headers": PRODUCT_HEADERS,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def product_import_csv(request):
    organization, response = _organization_or_redirect(request)
    if response:
        return response
    if not policies.can_manage_products(user=request.user, organization=organization):
        return redirect("products:list")
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
                "products/import_mapping.html",
                {
                    "organization": organization,
                    "canonical_headers": PRODUCT_HEADERS,
                    "required_headers": REQUIRED_PRODUCT_HEADERS,
                    "source_headers": source_headers,
                    "blank_mapping": BLANK_MAPPING,
                    "stage": dump_stage(headers=source_headers, rows=source_rows),
                },
            )

        if step == "mapping":
            source_headers, source_rows = load_stage(request.POST.get("stage", ""))
            mapping = mapping_from_post(
                canonical_headers=PRODUCT_HEADERS,
                source_headers=source_headers,
                post=request.POST,
            )
            for required in REQUIRED_PRODUCT_HEADERS:
                if mapping[required] == BLANK_MAPPING:
                    raise TabularImportError(f"Mapeie o campo obrigatório {required}.")
            rows = apply_mapping(
                canonical_headers=PRODUCT_HEADERS,
                rows=source_rows,
                mapping=mapping,
            )
            groups, errors, conflicts = _validate_product_rows(organization=organization, rows=rows)
            return render(
                request,
                "products/import_preview.html",
                {
                    "organization": organization,
                    "headers": PRODUCT_HEADERS,
                    "rows": rows[:20],
                    "row_count": len(rows),
                    "product_count": len(groups),
                    "errors": errors,
                    "conflicts": conflicts,
                    "can_confirm": not errors and not conflicts,
                    "stage": dump_stage(headers=PRODUCT_HEADERS, rows=rows),
                },
            )

        if step != "confirm":
            raise TabularImportError("Etapa de importação inválida.")
        stage_headers, rows = load_stage(request.POST.get("stage", ""))
        if stage_headers != PRODUCT_HEADERS:
            raise TabularImportError("Prévia canônica inválida.")

        source_digest = import_batch_digest(
            domain=DataImportBatchReceipt.Domain.PRODUCTS,
            headers=PRODUCT_HEADERS,
            rows=rows,
        )
        existing_batch = DataImportBatchReceipt.objects.filter(
            organization=organization,
            domain=DataImportBatchReceipt.Domain.PRODUCTS,
            source_digest=source_digest,
            completed=True,
        ).first()
        if existing_batch is not None:
            groups, errors = _group_product_rows(rows)
            if errors:
                raise TabularImportError("Lote importado possui estrutura canônica inválida.")
            return render(
                request,
                "products/import_result.html",
                {"organization": organization, "count": len(groups), "already_imported": True},
            )

        groups, errors, conflicts = _validate_product_rows(organization=organization, rows=rows)
        if errors or conflicts:
            raise TabularImportError("A prévia ficou obsoleta; revise validações e conflitos novamente.")

        with transaction.atomic():
            batch, is_new = claim_import_batch(
                organization=organization,
                domain=DataImportBatchReceipt.Domain.PRODUCTS,
                source_digest=source_digest,
                row_count=len(rows),
            )
            if not is_new:
                return render(
                    request,
                    "products/import_result.html",
                    {"organization": organization, "count": len(groups), "already_imported": True},
                )
            for group in groups.values():
                product = services.create_product(
                    organization=organization,
                    actor=request.user,
                    name=group["name"],
                    description=group["description"],
                    default_unit=group["default_unit"],
                )
                for entry in group["entries"]:
                    row = entry["row"]
                    if any((row[field] or "").strip() for field in ("variant_name", "sku", "barcode")):
                        services.create_variant(
                            organization=organization,
                            product=product,
                            actor=request.user,
                            name=row["variant_name"],
                            sku=row["sku"],
                            barcode=row["barcode"],
                        )
                    record_import_row(
                        batch=batch,
                        row_number=entry["row_number"],
                        row_digest=import_row_digest(headers=PRODUCT_HEADERS, row=row),
                        entity_id=product.id,
                    )
            complete_import_batch(batch=batch)
        return render(
            request,
            "products/import_result.html",
            {"organization": organization, "count": len(groups), "already_imported": False},
        )
    except (TabularImportError, ProductDomainError, ImportReceiptConflict) as exc:
        messages.error(request, f"Importação cancelada: {exc}")
        return _render_upload(request, organization=organization)
