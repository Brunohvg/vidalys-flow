import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.organizations.models import Membership
from apps.platform.models import OutboxEvent
from apps.products import selectors, services
from apps.products.exceptions import (
    DuplicateBarcodeError,
    DuplicateIdentifierError,
    DuplicateSkuError,
    ProductOrganizationMismatch,
    ProductPermissionDenied,
)
from apps.products.models import Product, ProductIdentifier, ProductVariant


def create_product(organization, actor, **overrides):
    values = {"name": "Produto Operacional", "description": "Descrição", "default_unit": "UN"}
    values.update(overrides)
    return services.create_product(organization=organization, actor=actor, **values)


@pytest.mark.django_db
def test_create_product_records_sanitized_audit_and_outbox(
    organization,
    user,
    operator_membership,
):
    product = create_product(organization, user)
    assert product.status == Product.Status.ACTIVE
    assert product.default_unit == "un"
    assert AuditEvent.objects.filter(action="product.created", entity_id=str(product.id)).exists()
    assert OutboxEvent.objects.filter(event_type="product.created", aggregate_id=str(product.id)).exists()


@pytest.mark.django_db
def test_service_requires_active_membership(organization, outsider):
    with pytest.raises(ProductPermissionDenied):
        create_product(organization, outsider)


@pytest.mark.django_db
def test_create_variant_normalizes_sku_and_is_unique_per_organization(
    organization,
    other_organization,
    user,
    outsider,
    operator_membership,
):
    Membership.objects.create(
        organization=other_organization,
        user=outsider,
        role=Membership.Role.OPERATOR,
    )
    first_product = create_product(organization, user, name="Primeiro")
    second_product = create_product(organization, user, name="Segundo")
    other_product = create_product(other_organization, outsider, name="Outro tenant")
    variant = services.create_variant(
        organization=organization,
        product=first_product,
        actor=user,
        sku=" sku-001 ",
    )
    assert variant.sku == "SKU-001"
    with pytest.raises(DuplicateSkuError):
        services.create_variant(
            organization=organization,
            product=second_product,
            actor=user,
            sku="Sku-001",
        )
    other = services.create_variant(
        organization=other_organization,
        product=other_product,
        actor=outsider,
        sku="sku-001",
    )
    assert other.sku == "SKU-001"


@pytest.mark.django_db
def test_database_sku_constraint_is_case_insensitive(organization):
    first = Product.objects.create(organization=organization, name="A")
    second = Product.objects.create(organization=organization, name="B")
    ProductVariant.objects.create(organization=organization, product=first, sku="ABC")
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductVariant.objects.create(organization=organization, product=second, sku="abc")


@pytest.mark.django_db
def test_identifier_is_normalized_idempotent_and_conflict_safe(
    organization,
    user,
    operator_membership,
):
    first = create_product(organization, user, name="Primeiro")
    second = create_product(organization, user, name="Segundo")
    identifier = services.add_identifier(
        organization=organization,
        product=first,
        actor=user,
        kind=ProductIdentifier.Kind.INTERNAL_CODE,
        value=" ref-1 ",
    )
    same = services.add_identifier(
        organization=organization,
        product=first,
        actor=user,
        kind=ProductIdentifier.Kind.INTERNAL_CODE,
        value="REF-1",
    )
    assert identifier == same
    assert identifier.value == "REF-1"
    with pytest.raises(DuplicateIdentifierError):
        services.add_identifier(
            organization=organization,
            product=second,
            actor=user,
            kind=ProductIdentifier.Kind.INTERNAL_CODE,
            value="ref-1",
        )


@pytest.mark.django_db
def test_selectors_never_cross_organizations(
    organization,
    other_organization,
    user,
    outsider,
    operator_membership,
):
    Membership.objects.create(
        organization=other_organization,
        user=outsider,
        role=Membership.Role.OPERATOR,
    )
    visible = create_product(organization, user, name="Produto local")
    create_product(other_organization, outsider, name="Produto externo")
    assert list(selectors.search_products(organization=organization)) == [visible]


@pytest.mark.django_db
def test_update_and_deactivate_are_audited(organization, user, operator_membership):
    product = create_product(organization, user)
    services.update_product(
        organization=organization,
        product=product,
        actor=user,
        name="Atualizado",
        description="Nova",
        default_unit="pc",
    )
    services.set_product_status(
        organization=organization,
        product=product,
        actor=user,
        status=Product.Status.INACTIVE,
        reason="Fora de linha",
    )
    product.refresh_from_db()
    assert product.name == "Atualizado"
    assert product.status == Product.Status.INACTIVE
    assert AuditEvent.objects.filter(entity_id=str(product.id), action="product.updated").exists()
    assert AuditEvent.objects.filter(entity_id=str(product.id), action="product.status_changed").exists()


@pytest.mark.django_db
def test_operator_cannot_archive_but_manager_can(
    organization,
    user,
    manager,
    operator_membership,
    manager_membership,
):
    product = create_product(organization, user)
    with pytest.raises(ProductPermissionDenied):
        services.set_product_status(
            organization=organization,
            product=product,
            actor=user,
            status=Product.Status.ARCHIVED,
        )
    services.set_product_status(
        organization=organization,
        product=product,
        actor=manager,
        status=Product.Status.ARCHIVED,
    )
    product.refresh_from_db()
    assert product.status == Product.Status.ARCHIVED


@pytest.mark.django_db
def test_cross_organization_write_is_rejected(
    organization,
    other_organization,
    user,
    operator_membership,
):
    product = Product.objects.create(organization=other_organization, name="Outro")
    with pytest.raises(ProductOrganizationMismatch):
        services.update_product(
            organization=organization,
            product=product,
            actor=user,
            name="Ataque",
            description="",
            default_unit="un",
        )


@pytest.mark.django_db
def test_inactive_membership_blocks_product_service(organization, user, operator_membership):
    operator_membership.is_active = False
    operator_membership.save(update_fields=("is_active",))
    with pytest.raises(ProductPermissionDenied):
        create_product(organization, user)


@pytest.mark.django_db
def test_duplicate_barcode_is_rejected(organization, user, operator_membership):
    first = create_product(organization, user, name="Primeiro")
    second = create_product(organization, user, name="Segundo")
    services.create_variant(
        organization=organization,
        product=first,
        actor=user,
        barcode="789 123",
    )
    with pytest.raises(DuplicateBarcodeError):
        services.create_variant(
            organization=organization,
            product=second,
            actor=user,
            barcode="789123",
        )
