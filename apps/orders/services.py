import unicodedata
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_event
from apps.orders import policies
from apps.orders.calculations import calculate_line, calculate_order, money
from apps.orders.calculations import quantity as normalize_quantity
from apps.orders.events import (
    ORDER_CANCELLED,
    ORDER_CONFIRMED,
    ORDER_CREATED,
    ORDER_CUSTOMER_CHANGED,
    ORDER_ITEM_ADDED,
    ORDER_ITEM_REMOVED,
    ORDER_ITEM_UPDATED,
)
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
from apps.orders.idempotency import claim_command, complete_command
from apps.orders.models import Order, OrderItem, OrderStatusHistory
from apps.orders.numbering import allocate_order_number
from apps.orders.snapshots import customer_snapshots
from apps.orders.transitions import ensure_transition
from apps.platform.services import enqueue_event
from apps.products.models import Product


def _require_permission(*, actor, organization, action):
    checks = {
        "manage": policies.can_manage_drafts,
        "confirm": policies.can_confirm_orders,
        "adjust": policies.can_apply_adjustments,
        "cancel": policies.can_cancel_orders,
    }
    if not checks[action](user=actor, organization=organization):
        raise OrderPermissionDenied("Membership ativa ou papel insuficiente.")


def _require_customer(*, organization, customer):
    if customer.organization_id != organization.id:
        raise OrganizationMismatch("Cliente não pertence à organização.")
    if customer.merged_into_id:
        raise ConfirmationBlocked("Selecione explicitamente o cliente canônico.")


def _lock_order(*, organization, order):
    locked = Order.objects.select_for_update().filter(organization=organization, id=order.id).first()
    if not locked:
        raise OrganizationMismatch("Pedido não pertence à organização.")
    return locked


def _ensure_draft(order):
    if not order.is_editable:
        raise OrderNotEditable("Somente pedidos em rascunho podem ser editados.")


def _ensure_version(*, order, expected_version):
    if order.version != expected_version:
        raise VersionConflict(
            f"Pedido alterado por outro usuário (versão atual {order.version}, recebida {expected_version})."
        )


def _finish_mutation(order):
    order.version += 1
    order.save(update_fields=("version", "updated_at"))


def _audit(*, order, actor, action, payload):
    record_event(
        organization=order.organization,
        actor=actor,
        action=action,
        entity_type="order",
        entity_id=order.id,
        payload={"order_number": order.display_number, "version": order.version, **payload},
    )


def _outbox(*, order, event_type, command_id):
    enqueue_event(
        organization=order.organization,
        event_type=event_type,
        aggregate_type="order",
        aggregate_id=order.id,
        payload={
            "order_id": str(order.id),
            "order_number": order.display_number,
            "status": order.status,
            "version": order.version,
        },
        idempotency_key=f"order:{order.id}:{event_type}:{command_id}",
    )


def _existing_result(receipt, *, item=False):
    if item:
        result = OrderItem.objects.filter(
            organization=receipt.organization,
            order=receipt.order,
            id=receipt.result_item_id,
        ).first()
        if result is None:
            raise IdempotencyConflict("O item resultante deste comando não existe mais.")
        return result
    result = Order.objects.filter(organization=receipt.organization, id=receipt.order_id).first()
    if result is None:
        raise IdempotencyConflict("O pedido resultante deste comando não existe mais.")
    return result


def _recalculate(order):
    totals = calculate_order(order.items.all())
    for field, value in totals.items():
        setattr(order, field, value)
    order.save(update_fields=(*totals.keys(), "updated_at"))


def _normalized_text(value):
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


def _validate_surcharge(*, amount, reason):
    if amount == Decimal("0.00"):
        if reason.strip():
            raise InvalidItem("Motivo de acréscimo só deve ser informado quando houver acréscimo.")
        return
    if not reason.strip():
        raise ReasonRequired("Todo acréscimo exige motivo.")
    normalized = _normalized_text(reason)
    forbidden = ("frete", "shipping", "imposto", "tributo", "juros", "interest", "taxa de pagamento")
    if any(term in normalized for term in forbidden) or "tax" in normalized.split():
        raise InvalidItem("Acréscimo não pode representar frete, tributo, juros ou taxa de pagamento.")


def _validate_catalog_item(*, organization, product, variant, confirmation=False):
    if variant and product is None:
        product = variant.product
    if product and product.organization_id != organization.id:
        raise OrganizationMismatch("Produto não pertence à organização.")
    if variant:
        if variant.organization_id != organization.id:
            raise OrganizationMismatch("Variação não pertence à organização.")
        if variant.product_id != product.id:
            raise InvalidItem("A variação não pertence ao produto.")
    if product and product.status != Product.Status.ACTIVE:
        message = "Produto inativo ou arquivado bloqueia a confirmação." if confirmation else "Produto indisponível."
        raise ConfirmationBlocked(message)
    if variant and variant.status != Product.Status.ACTIVE:
        message = "Variação inativa ou arquivada bloqueia a confirmação." if confirmation else "Variação indisponível."
        raise ConfirmationBlocked(message)
    return product


@transaction.atomic
def create_order(*, organization, customer, actor, channel="", idempotency_key):
    _require_permission(actor=actor, organization=organization, action="manage")
    _require_customer(organization=organization, customer=customer)
    payload = {"customer_id": str(customer.id), "channel": channel.strip()}
    receipt, is_new = claim_command(
        organization=organization,
        operation="create_order",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)
    number = allocate_order_number(organization=organization)
    order = Order.objects.create(
        organization=organization,
        number=number,
        customer=customer,
        channel=channel.strip(),
        created_by=actor,
    )
    OrderStatusHistory.objects.create(
        organization=organization,
        order=order,
        from_status="",
        to_status=Order.Status.DRAFT,
        actor=actor,
        command_id=str(idempotency_key),
    )
    _audit(order=order, actor=actor, action=ORDER_CREATED, payload={"status": order.status})
    _outbox(order=order, event_type=ORDER_CREATED, command_id=idempotency_key)
    complete_command(receipt=receipt, order=order)
    return order


@transaction.atomic
def change_customer(*, organization, order, customer, actor, expected_version, idempotency_key):
    _require_permission(actor=actor, organization=organization, action="manage")
    _require_customer(organization=organization, customer=customer)
    payload = {
        "order_id": str(order.id),
        "customer_id": str(customer.id),
        "expected_version": expected_version,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="change_customer",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)
    order = _lock_order(organization=organization, order=order)
    _ensure_draft(order)
    _ensure_version(order=order, expected_version=expected_version)
    order.customer = customer
    order.version += 1
    order.save(update_fields=("customer", "version", "updated_at"))
    _audit(
        order=order,
        actor=actor,
        action=ORDER_CUSTOMER_CHANGED,
        payload={"changed_fields": ["customer"]},
    )
    complete_command(receipt=receipt, order=order)
    return order


@transaction.atomic
def add_item(
    *,
    organization,
    order,
    actor,
    expected_version,
    idempotency_key,
    quantity,
    unit_price,
    product=None,
    variant=None,
    name="",
    unit="un",
    discount_amount=0,
    surcharge_amount=0,
    surcharge_reason="",
    notes="",
):
    _require_permission(actor=actor, organization=organization, action="manage")
    line = calculate_line(
        item_quantity=quantity,
        unit_price=unit_price,
        discount_amount=discount_amount,
        surcharge_amount=surcharge_amount,
    )
    if line.discount_amount or line.surcharge_amount:
        _require_permission(actor=actor, organization=organization, action="adjust")
    _validate_surcharge(amount=line.surcharge_amount, reason=surcharge_reason)
    product = _validate_catalog_item(organization=organization, product=product, variant=variant)
    item_name = (name or (product.name if product else "")).strip()
    if not item_name:
        raise InvalidItem("Item avulso exige nome.")
    payload = {
        "order_id": str(order.id),
        "expected_version": expected_version,
        "product_id": str(product.id) if product else None,
        "variant_id": str(variant.id) if variant else None,
        "name": item_name,
        "unit": unit,
        "quantity": str(line.quantity),
        "unit_price": str(line.unit_price),
        "discount_amount": str(line.discount_amount),
        "surcharge_amount": str(line.surcharge_amount),
        "surcharge_reason": surcharge_reason.strip(),
        "notes": notes.strip(),
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="add_item",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt, item=True)
    order = _lock_order(organization=organization, order=order)
    _ensure_draft(order)
    _ensure_version(order=order, expected_version=expected_version)
    position = (order.items.aggregate(value=Max("position"))["value"] or 0) + 1
    item = OrderItem.objects.create(
        organization=organization,
        order=order,
        position=position,
        product=product,
        variant=variant,
        name_snapshot=item_name,
        variant_snapshot=variant.name if variant else "",
        sku_snapshot=variant.sku if variant else "",
        unit_snapshot=(product.default_unit if product else unit).strip().lower() or "un",
        quantity=line.quantity,
        unit_price=line.unit_price,
        gross_total=line.gross_total,
        discount_amount=line.discount_amount,
        surcharge_amount=line.surcharge_amount,
        surcharge_reason=surcharge_reason.strip(),
        total=line.total,
        notes=notes.strip(),
    )
    _recalculate(order)
    _finish_mutation(order)
    _audit(
        order=order,
        actor=actor,
        action=ORDER_ITEM_ADDED,
        payload={"item_id": str(item.id), "changed_fields": ["items", "totals"]},
    )
    complete_command(receipt=receipt, order=order, item=item)
    return item


@transaction.atomic
def update_item(
    *,
    organization,
    item,
    actor,
    expected_version,
    idempotency_key,
    quantity=None,
    unit_price=None,
    discount_amount=None,
    surcharge_amount=None,
    surcharge_reason=None,
    notes=None,
):
    _require_permission(actor=actor, organization=organization, action="manage")
    payload = {
        "order_id": str(item.order_id),
        "item_id": str(item.id),
        "expected_version": expected_version,
        "quantity": str(normalize_quantity(quantity)) if quantity is not None else None,
        "unit_price": str(money(unit_price)) if unit_price is not None else None,
        "discount_amount": str(money(discount_amount)) if discount_amount is not None else None,
        "surcharge_amount": str(money(surcharge_amount)) if surcharge_amount is not None else None,
        "surcharge_reason": surcharge_reason.strip() if surcharge_reason is not None else None,
        "notes": notes.strip() if notes is not None else None,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="update_item",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt, item=True)
    order = _lock_order(organization=organization, order=item.order)
    _ensure_draft(order)
    _ensure_version(order=order, expected_version=expected_version)
    item = OrderItem.objects.filter(organization=organization, order=order, id=item.id).first()
    if not item:
        raise OrganizationMismatch("Item não pertence ao pedido e à organização.")
    line = calculate_line(
        item_quantity=item.quantity if quantity is None else quantity,
        unit_price=item.unit_price if unit_price is None else unit_price,
        discount_amount=item.discount_amount if discount_amount is None else discount_amount,
        surcharge_amount=item.surcharge_amount if surcharge_amount is None else surcharge_amount,
    )
    new_reason = item.surcharge_reason if surcharge_reason is None else surcharge_reason.strip()
    if item.discount_amount or item.surcharge_amount or line.discount_amount or line.surcharge_amount:
        _require_permission(actor=actor, organization=organization, action="adjust")
    _validate_surcharge(amount=line.surcharge_amount, reason=new_reason)
    changed_fields = []
    values = {
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "gross_total": line.gross_total,
        "discount_amount": line.discount_amount,
        "surcharge_amount": line.surcharge_amount,
        "surcharge_reason": new_reason,
        "total": line.total,
        "notes": item.notes if notes is None else notes.strip(),
    }
    for field, value in values.items():
        if getattr(item, field) != value:
            setattr(item, field, value)
            changed_fields.append(field)
    item.save(update_fields=(*changed_fields, "updated_at"))
    _recalculate(order)
    _finish_mutation(order)
    _audit(
        order=order,
        actor=actor,
        action=ORDER_ITEM_UPDATED,
        payload={"item_id": str(item.id), "changed_fields": changed_fields},
    )
    complete_command(receipt=receipt, order=order, item=item)
    return item


@transaction.atomic
def remove_item(*, organization, item, actor, expected_version, idempotency_key):
    _require_permission(actor=actor, organization=organization, action="manage")
    payload = {
        "order_id": str(item.order_id),
        "item_id": str(item.id),
        "expected_version": expected_version,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="remove_item",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)
    order = _lock_order(organization=organization, order=item.order)
    _ensure_draft(order)
    _ensure_version(order=order, expected_version=expected_version)
    item = OrderItem.objects.filter(organization=organization, order=order, id=item.id).first()
    if not item:
        raise OrganizationMismatch("Item não pertence ao pedido e à organização.")
    item_id = item.id
    item.delete()
    _recalculate(order)
    _finish_mutation(order)
    _audit(
        order=order,
        actor=actor,
        action=ORDER_ITEM_REMOVED,
        payload={"item_id": str(item_id), "changed_fields": ["items", "totals"]},
    )
    complete_command(receipt=receipt, order=order)
    return order


@transaction.atomic
def confirm_order(*, organization, order, actor, expected_version, idempotency_key):
    _require_permission(actor=actor, organization=organization, action="confirm")
    payload = {"order_id": str(order.id), "expected_version": expected_version}
    receipt, is_new = claim_command(
        organization=organization,
        operation="confirm_order",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)
    order = _lock_order(organization=organization, order=order)
    _ensure_version(order=order, expected_version=expected_version)
    ensure_transition(from_status=order.status, to_status=Order.Status.CONFIRMED)
    _require_customer(organization=organization, customer=order.customer)
    items = list(order.items.select_related("product", "variant"))
    if not items:
        raise ConfirmationBlocked("Pedido sem itens não pode ser confirmado.")
    for item in items:
        _validate_catalog_item(
            organization=organization,
            product=item.product,
            variant=item.variant,
            confirmation=True,
        )
        snapshot_updates = {}
        if item.product:
            snapshot_updates.update(
                name_snapshot=item.product.name,
                unit_snapshot=item.product.default_unit,
            )
        if item.variant:
            snapshot_updates.update(
                variant_snapshot=item.variant.name,
                sku_snapshot=item.variant.sku,
            )
        changed_fields = []
        for field, value in snapshot_updates.items():
            if getattr(item, field) != value:
                setattr(item, field, value)
                changed_fields.append(field)
        if changed_fields:
            item.save(update_fields=(*changed_fields, "updated_at"))
    _recalculate(order)
    for field, value in customer_snapshots(order.customer).items():
        setattr(order, field, value)
    order.status = Order.Status.CONFIRMED
    order.confirmed_at = timezone.now()
    order.version += 1
    order.save(
        update_fields=(
            "customer_name_snapshot",
            "customer_document_snapshot",
            "customer_contact_snapshot",
            "shipping_address_snapshot",
            "billing_address_snapshot",
            "snapshot_schema_version",
            "status",
            "confirmed_at",
            "version",
            "updated_at",
        )
    )
    OrderStatusHistory.objects.create(
        organization=organization,
        order=order,
        from_status=Order.Status.DRAFT,
        to_status=Order.Status.CONFIRMED,
        actor=actor,
        command_id=str(idempotency_key),
    )
    _audit(
        order=order,
        actor=actor,
        action=ORDER_CONFIRMED,
        payload={"before": Order.Status.DRAFT, "after": Order.Status.CONFIRMED, "total": str(order.total)},
    )
    _outbox(order=order, event_type=ORDER_CONFIRMED, command_id=idempotency_key)
    complete_command(receipt=receipt, order=order)
    return order


@transaction.atomic
def cancel_order(*, organization, order, actor, reason, expected_version, idempotency_key):
    _require_permission(actor=actor, organization=organization, action="cancel")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ReasonRequired("Cancelamento exige motivo.")
    payload = {
        "order_id": str(order.id),
        "reason": normalized_reason,
        "expected_version": expected_version,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="cancel_order",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)
    order = _lock_order(organization=organization, order=order)
    _ensure_version(order=order, expected_version=expected_version)
    before = order.status
    ensure_transition(from_status=before, to_status=Order.Status.CANCELLED)
    order.status = Order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancel_reason = normalized_reason
    order.version += 1
    order.save(update_fields=("status", "cancelled_at", "cancel_reason", "version", "updated_at"))
    OrderStatusHistory.objects.create(
        organization=organization,
        order=order,
        from_status=before,
        to_status=Order.Status.CANCELLED,
        actor=actor,
        command_id=str(idempotency_key),
        reason_provided=True,
    )
    _audit(
        order=order,
        actor=actor,
        action=ORDER_CANCELLED,
        payload={"before": before, "after": Order.Status.CANCELLED, "reason_provided": True},
    )
    _outbox(order=order, event_type=ORDER_CANCELLED, command_id=idempotency_key)
    complete_command(receipt=receipt, order=order)
    return order
