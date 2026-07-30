import uuid
from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.customers.models import ContactPoint, Customer
from apps.customers.services import add_address, add_contact
from apps.orders.events import ORDER_CANCELLED, ORDER_CONFIRMED
from apps.orders.exceptions import (
    ConfirmationBlocked,
    IdempotencyConflict,
    InvalidItem,
    OrderNotEditable,
    OrderPermissionDenied,
    OrganizationMismatch,
    ReasonRequired,
    VersionConflict,
)
from apps.orders.models import Order, OrderCommandReceipt, OrderItem, OrderStatusHistory
from apps.orders.services import (
    add_item,
    cancel_order,
    change_customer,
    confirm_order,
    create_order,
    remove_item,
    update_item,
)
from apps.organizations.models import Membership
from apps.platform.models import OutboxEvent
from apps.products.models import Product
from apps.products.services import create_product, create_variant


def key():
    return str(uuid.uuid4())


@pytest.mark.django_db
def test_create_is_idempotent_and_numbered_per_organization(
    organization,
    other_organization,
    customer,
    user,
    operator_membership,
):
    first_key = key()
    first = create_order(
        organization=organization,
        customer=customer,
        actor=user,
        idempotency_key=first_key,
    )
    retry = create_order(
        organization=organization,
        customer=customer,
        actor=user,
        idempotency_key=first_key,
    )
    second = create_order(
        organization=organization,
        customer=customer,
        actor=user,
        idempotency_key=key(),
    )
    other_customer = Customer.objects.create(
        organization=other_organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Outra organização",
    )
    Membership.objects.create(organization=other_organization, user=user, role=Membership.Role.OPERATOR)
    other = create_order(
        organization=other_organization,
        customer=other_customer,
        actor=user,
        idempotency_key=key(),
    )
    assert (first.number, retry.id, second.number, other.number) == (1, first.id, 2, 1)
    assert first.display_number == "PED-000001"
    assert OrderCommandReceipt.objects.filter(operation="create_order").count() == 3


@pytest.mark.django_db
def test_same_idempotency_key_with_different_payload_conflicts(organization, customer, user):
    command_key = key()
    create_order(
        organization=organization,
        customer=customer,
        actor=user,
        channel="site",
        idempotency_key=command_key,
    )
    with pytest.raises(IdempotencyConflict):
        create_order(
            organization=organization,
            customer=customer,
            actor=user,
            channel="loja",
            idempotency_key=command_key,
        )


@pytest.mark.django_db
def test_cross_organization_customer_is_refused(other_organization, customer, user):
    Membership.objects.create(organization=other_organization, user=user, role=Membership.Role.OPERATOR)
    with pytest.raises(OrganizationMismatch):
        create_order(
            organization=other_organization,
            customer=customer,
            actor=user,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_cross_organization_product_is_refused(
    organization,
    other_organization,
    order,
    user,
):
    Membership.objects.create(organization=other_organization, user=user, role=Membership.Role.OPERATOR)
    product = create_product(organization=other_organization, actor=user, name="Produto externo")
    with pytest.raises(OrganizationMismatch):
        add_item(
            organization=organization,
            order=order,
            actor=user,
            expected_version=1,
            idempotency_key=key(),
            product=product,
            quantity=1,
            unit_price=10,
        )


@pytest.mark.django_db
def test_free_item_recalculates_totals_from_persisted_lines(organization, order, user):
    first = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
        name="Tecido",
        unit="m",
        quantity="0.333",
        unit_price="0.05",
    )
    second = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=2,
        idempotency_key=key(),
        name="Tecido",
        unit="m",
        quantity="0.333",
        unit_price="0.05",
    )
    order.refresh_from_db()
    assert first.gross_total == second.gross_total == Decimal("0.02")
    assert order.subtotal == order.total == Decimal("0.04")
    assert order.version == 3


@pytest.mark.django_db
def test_add_item_command_is_idempotent(organization, order, user):
    command_key = key()
    first = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=command_key,
        name="Item",
        quantity=1,
        unit_price=10,
    )
    retry = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=command_key,
        name="Item",
        quantity=1,
        unit_price=10,
    )
    assert retry.id == first.id
    assert order.items.count() == 1


@pytest.mark.django_db
def test_retry_of_item_command_reports_result_removed(organization, order, user):
    command_key = key()
    item = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=command_key,
        name="Item",
        quantity=1,
        unit_price=10,
    )
    remove_item(
        organization=organization,
        item=item,
        actor=user,
        expected_version=2,
        idempotency_key=key(),
    )
    with pytest.raises(IdempotencyConflict, match="não existe mais"):
        add_item(
            organization=organization,
            order=order,
            actor=user,
            expected_version=1,
            idempotency_key=command_key,
            name="Item",
            quantity=1,
            unit_price=10,
        )


@pytest.mark.django_db
def test_operator_cannot_apply_discount_or_surcharge(organization, order, user):
    with pytest.raises(OrderPermissionDenied):
        add_item(
            organization=organization,
            order=order,
            actor=user,
            expected_version=1,
            idempotency_key=key(),
            name="Item",
            quantity=1,
            unit_price=10,
            discount_amount=1,
        )


@pytest.mark.django_db
def test_manager_adjustments_require_valid_reason(organization, customer, manager, manager_membership):
    manager_order = create_order(
        organization=organization,
        customer=customer,
        actor=manager,
        idempotency_key=key(),
    )
    with pytest.raises(ReasonRequired):
        add_item(
            organization=organization,
            order=manager_order,
            actor=manager,
            expected_version=1,
            idempotency_key=key(),
            name="Item",
            quantity=1,
            unit_price=10,
            surcharge_amount=1,
        )
    with pytest.raises(InvalidItem):
        add_item(
            organization=organization,
            order=manager_order,
            actor=manager,
            expected_version=1,
            idempotency_key=key(),
            name="Item",
            quantity=1,
            unit_price=10,
            surcharge_amount=1,
            surcharge_reason="Frete",
        )
    item = add_item(
        organization=organization,
        order=manager_order,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
        name="Item",
        quantity=1,
        unit_price=10,
        discount_amount=2,
        surcharge_amount=1,
        surcharge_reason="Personalização adicional",
    )
    assert item.total == Decimal("9.00")


@pytest.mark.django_db
def test_catalog_snapshots_and_variant_invariant(
    organization,
    order,
    user,
):
    product = create_product(organization=organization, actor=user, name="Camiseta", default_unit="un")
    variant = create_variant(
        organization=organization,
        product=product,
        actor=user,
        name="Azul M",
        sku="CAM-AZ-M",
    )
    item = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
        product=product,
        variant=variant,
        quantity=1,
        unit_price=50,
    )
    assert item.name_snapshot == "Camiseta"
    assert item.variant_snapshot == "Azul M"
    assert item.sku_snapshot == "CAM-AZ-M"
    other = create_product(organization=organization, actor=user, name="Outro")
    with pytest.raises(InvalidItem):
        add_item(
            organization=organization,
            order=order,
            actor=user,
            expected_version=2,
            idempotency_key=key(),
            product=other,
            variant=variant,
            quantity=1,
            unit_price=1,
        )


@pytest.mark.django_db
def test_update_remove_and_version_conflict(organization, order, user):
    item = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
        name="Item",
        quantity=1,
        unit_price=10,
    )
    with pytest.raises(VersionConflict):
        update_item(
            organization=organization,
            item=item,
            actor=user,
            expected_version=1,
            idempotency_key=key(),
            quantity=2,
        )
    updated = update_item(
        organization=organization,
        item=item,
        actor=user,
        expected_version=2,
        idempotency_key=key(),
        quantity=2,
    )
    assert updated.total == Decimal("20.00")
    result = remove_item(
        organization=organization,
        item=updated,
        actor=user,
        expected_version=3,
        idempotency_key=key(),
    )
    assert result.total == Decimal("0.00")
    assert not OrderItem.objects.filter(id=item.id).exists()


@pytest.mark.django_db
def test_change_customer_requires_explicit_canonical(organization, order, customer, user):
    merged = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Mesclado",
        status=Customer.Status.INACTIVE,
        merged_into=customer,
    )
    with pytest.raises(ConfirmationBlocked):
        change_customer(
            organization=organization,
            order=order,
            customer=merged,
            actor=user,
            expected_version=1,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_change_customer_succeeds_for_explicit_canonical(organization, order, user):
    new_customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente canônico",
    )
    changed = change_customer(
        organization=organization,
        order=order,
        customer=new_customer,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
    )
    assert changed.customer_id == new_customer.id
    assert changed.version == 2


@pytest.mark.django_db
def test_confirmation_requires_items(organization, order, user):
    with pytest.raises(ConfirmationBlocked):
        confirm_order(
            organization=organization,
            order=order,
            actor=user,
            expected_version=1,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_confirmation_freezes_closed_snapshots_and_is_idempotent(organization, order, customer, user):
    add_contact(
        organization=organization,
        customer=customer,
        actor=user,
        kind=ContactPoint.Kind.PHONE,
        value="11999991234",
        is_primary=True,
    )
    add_address(
        organization=organization,
        customer=customer,
        actor=user,
        street="Rua A",
        number="10",
        city="São Paulo",
        state="SP",
        country="BR",
        is_default_shipping=True,
        is_default_billing=True,
    )
    add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
        name="Item",
        quantity=1,
        unit_price=10,
    )
    command_key = key()
    confirmed = confirm_order(
        organization=organization,
        order=order,
        actor=user,
        expected_version=2,
        idempotency_key=command_key,
    )
    retry = confirm_order(
        organization=organization,
        order=order,
        actor=user,
        expected_version=2,
        idempotency_key=command_key,
    )
    assert retry.id == confirmed.id
    assert confirmed.customer_document_snapshot == "52998224725"
    assert set(confirmed.customer_contact_snapshot) == {"schema_version", "kind", "value"}
    assert set(confirmed.shipping_address_snapshot) == {
        "schema_version",
        "recipient_name",
        "postal_code",
        "street",
        "number",
        "complement",
        "district",
        "city",
        "state",
        "country",
    }
    customer.display_name = "Nome alterado"
    customer.save(update_fields=("display_name", "updated_at"))
    confirmed.refresh_from_db()
    assert confirmed.customer_name_snapshot == "Cliente do pedido"
    assert OrderStatusHistory.objects.filter(order=order, to_status=Order.Status.CONFIRMED).count() == 1
    assert OutboxEvent.objects.filter(aggregate_id=str(order.id), event_type=ORDER_CONFIRMED).count() == 1


@pytest.mark.django_db
def test_confirmation_blocks_merged_customer(organization, order, customer, user):
    canonical = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Canônico",
    )
    add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
        name="Item",
        quantity=1,
        unit_price=10,
    )
    customer.merged_into = canonical
    customer.status = Customer.Status.INACTIVE
    customer.save(update_fields=("merged_into", "status", "updated_at"))
    with pytest.raises(ConfirmationBlocked):
        confirm_order(
            organization=organization,
            order=order,
            actor=user,
            expected_version=2,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_confirmation_blocks_inactive_product(organization, order, user):
    product = create_product(organization=organization, actor=user, name="Produto")
    add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
        product=product,
        quantity=1,
        unit_price=10,
    )
    product.status = Product.Status.INACTIVE
    product.save(update_fields=("status", "updated_at"))
    with pytest.raises(ConfirmationBlocked):
        confirm_order(
            organization=organization,
            order=order,
            actor=user,
            expected_version=2,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_confirmation_blocks_inactive_variant(organization, order, user):
    product = create_product(organization=organization, actor=user, name="Produto")
    variant = create_variant(
        organization=organization,
        product=product,
        actor=user,
        name="Variação",
        sku="VAR-1",
    )
    add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
        product=product,
        variant=variant,
        quantity=1,
        unit_price=10,
    )
    variant.status = Product.Status.ARCHIVED
    variant.save(update_fields=("status", "updated_at"))
    with pytest.raises(ConfirmationBlocked):
        confirm_order(
            organization=organization,
            order=order,
            actor=user,
            expected_version=2,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_confirmed_order_is_immutable_through_services(organization, order, user):
    item = add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=key(),
        name="Item",
        quantity=1,
        unit_price=10,
    )
    confirm_order(
        organization=organization,
        order=order,
        actor=user,
        expected_version=2,
        idempotency_key=key(),
    )
    with pytest.raises(OrderNotEditable):
        update_item(
            organization=organization,
            item=item,
            actor=user,
            expected_version=3,
            idempotency_key=key(),
            quantity=2,
        )


@pytest.mark.django_db
def test_only_manager_tier_cancels_and_reason_is_not_in_events(
    organization,
    order,
    user,
    manager,
    manager_membership,
):
    with pytest.raises(OrderPermissionDenied):
        cancel_order(
            organization=organization,
            order=order,
            actor=user,
            reason="Cliente desistiu",
            expected_version=1,
            idempotency_key=key(),
        )
    with pytest.raises(ReasonRequired):
        cancel_order(
            organization=organization,
            order=order,
            actor=manager,
            reason=" ",
            expected_version=1,
            idempotency_key=key(),
        )
    cancelled = cancel_order(
        organization=organization,
        order=order,
        actor=manager,
        reason="Cliente desistiu",
        expected_version=1,
        idempotency_key=key(),
    )
    audit = AuditEvent.objects.get(action=ORDER_CANCELLED, entity_id=str(order.id))
    event = OutboxEvent.objects.get(event_type=ORDER_CANCELLED, aggregate_id=str(order.id))
    assert cancelled.status == Order.Status.CANCELLED
    assert audit.payload["reason_provided"] is True
    assert "Cliente desistiu" not in str(audit.payload)
    assert "Cliente desistiu" not in str(event.payload)


@pytest.mark.django_db
def test_cancel_command_is_idempotent(organization, order, manager, manager_membership):
    command_key = key()
    first = cancel_order(
        organization=organization,
        order=order,
        actor=manager,
        reason="Cliente desistiu",
        expected_version=1,
        idempotency_key=command_key,
    )
    retry = cancel_order(
        organization=organization,
        order=order,
        actor=manager,
        reason="Cliente desistiu",
        expected_version=1,
        idempotency_key=command_key,
    )
    assert retry.id == first.id
    assert OrderStatusHistory.objects.filter(order=order, to_status=Order.Status.CANCELLED).count() == 1
    assert OutboxEvent.objects.filter(event_type=ORDER_CANCELLED, aggregate_id=str(order.id)).count() == 1


@pytest.mark.django_db
def test_status_history_is_separate_and_immutable(organization, order):
    history = OrderStatusHistory.objects.get(order=order)
    with pytest.raises(TypeError):
        history.delete()
    assert AuditEvent.objects.filter(entity_id=str(order.id)).exists()
