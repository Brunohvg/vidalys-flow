from django.db import IntegrityError, transaction

from apps.audit.services import record_event
from apps.platform.services import enqueue_event
from apps.products import policies
from apps.products.events import (
    PRODUCT_CREATED,
    PRODUCT_IDENTIFIER_ADDED,
    PRODUCT_STATUS_CHANGED,
    PRODUCT_UPDATED,
    PRODUCT_VARIANT_CREATED,
)
from apps.products.exceptions import (
    DuplicateBarcodeError,
    DuplicateIdentifierError,
    DuplicateSkuError,
    ProductOrganizationMismatch,
    ProductPermissionDenied,
    VariantProductMismatch,
)
from apps.products.models import Product, ProductIdentifier, ProductVariant
from apps.products.normalization import normalize_barcode, normalize_identifier, normalize_sku


def _require_permission(*, actor, organization, manager=False):
    allowed = (
        policies.can_archive_products(user=actor, organization=organization)
        if manager
        else policies.can_manage_products(user=actor, organization=organization)
    )
    if not allowed:
        raise ProductPermissionDenied("Membership ativa insuficiente.")


def _require_product(*, organization, product):
    if product.organization_id != organization.id:
        raise ProductOrganizationMismatch("Produto não pertence à organização.")


@transaction.atomic
def create_product(*, organization, actor, name, description="", default_unit="un"):
    _require_permission(actor=actor, organization=organization)
    product = Product.objects.create(
        organization=organization,
        name=name.strip(),
        description=description.strip(),
        default_unit=default_unit.strip().lower() or "un",
    )
    record_event(
        organization=organization,
        actor=actor,
        action=PRODUCT_CREATED,
        entity_type="product",
        entity_id=product.id,
        payload={},
    )
    enqueue_event(
        organization=organization,
        event_type=PRODUCT_CREATED,
        aggregate_type="product",
        aggregate_id=product.id,
        payload={"product_id": str(product.id)},
        idempotency_key=f"product-created-{product.id}",
    )
    return product


@transaction.atomic
def update_product(*, organization, product, actor, name, description="", default_unit="un"):
    _require_permission(actor=actor, organization=organization)
    _require_product(organization=organization, product=product)
    changed_fields = []
    values = {
        "name": name.strip(),
        "description": description.strip(),
        "default_unit": default_unit.strip().lower() or "un",
    }
    for field, value in values.items():
        if getattr(product, field) != value:
            setattr(product, field, value)
            changed_fields.append(field)
    if changed_fields:
        product.save(update_fields=(*changed_fields, "updated_at"))
        record_event(
            organization=organization,
            actor=actor,
            action=PRODUCT_UPDATED,
            entity_type="product",
            entity_id=product.id,
            payload={"changed_fields": changed_fields},
        )
    return product


@transaction.atomic
def set_product_status(*, organization, product, actor, status, reason=""):
    _require_permission(
        actor=actor,
        organization=organization,
        manager=status == Product.Status.ARCHIVED,
    )
    _require_product(organization=organization, product=product)
    if product.status == status:
        return product
    before = product.status
    product.status = status
    product.save(update_fields=("status", "updated_at"))
    record_event(
        organization=organization,
        actor=actor,
        action=PRODUCT_STATUS_CHANGED,
        entity_type="product",
        entity_id=product.id,
        payload={"before": before, "after": status, "reason_provided": bool(reason.strip())},
    )
    return product


@transaction.atomic
def create_variant(*, organization, product, actor, name="", sku="", barcode=""):
    _require_permission(actor=actor, organization=organization)
    _require_product(organization=organization, product=product)
    normalized_sku = normalize_sku(sku)
    normalized_barcode = normalize_barcode(barcode)
    try:
        with transaction.atomic():
            variant = ProductVariant.objects.create(
                organization=organization,
                product=product,
                name=name.strip(),
                sku=normalized_sku,
                barcode=normalized_barcode,
            )
    except IntegrityError as exc:
        if normalized_sku and ProductVariant.objects.filter(
            organization=organization,
            sku__iexact=normalized_sku,
        ).exists():
            raise DuplicateSkuError("SKU já cadastrado nesta organização.") from exc
        if normalized_barcode and ProductVariant.objects.filter(
            organization=organization,
            barcode=normalized_barcode,
        ).exists():
            raise DuplicateBarcodeError("Código de barras já cadastrado nesta organização.") from exc
        raise
    record_event(
        organization=organization,
        actor=actor,
        action=PRODUCT_VARIANT_CREATED,
        entity_type="product",
        entity_id=product.id,
        payload={"variant_id": str(variant.id)},
    )
    return variant


@transaction.atomic
def add_identifier(*, organization, product, actor, kind, value, variant=None):
    _require_permission(actor=actor, organization=organization)
    _require_product(organization=organization, product=product)
    if variant and (variant.organization_id != organization.id or variant.product_id != product.id):
        raise VariantProductMismatch("Variação não pertence ao produto e à organização.")
    normalized = normalize_identifier(kind, value)
    existing = ProductIdentifier.objects.filter(
        organization=organization,
        kind=kind,
        value__iexact=normalized,
    ).first()
    if existing:
        if existing.product_id == product.id and existing.variant_id == (variant.id if variant else None):
            return existing
        raise DuplicateIdentifierError("Identificador já vinculado nesta organização.")
    identifier = ProductIdentifier.objects.create(
        organization=organization,
        product=product,
        variant=variant,
        kind=kind,
        value=normalized,
    )
    record_event(
        organization=organization,
        actor=actor,
        action=PRODUCT_IDENTIFIER_ADDED,
        entity_type="product",
        entity_id=product.id,
        payload={"identifier_id": str(identifier.id), "kind": kind},
    )
    return identifier
