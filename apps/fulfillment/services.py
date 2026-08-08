import hashlib
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_event
from apps.fulfillment import policies
from apps.fulfillment.events import (
    FULFILLMENT_CANCELLED,
    FULFILLMENT_COMPLETED,
    FULFILLMENT_CREATED,
    FULFILLMENT_DISPATCHED,
    FULFILLMENT_PREPARING,
    FULFILLMENT_READY,
    FULFILLMENT_UPDATED,
)
from apps.fulfillment.exceptions import (
    FulfillmentPermissionDenied,
    IdempotencyConflict,
    InvalidFulfillment,
    OrganizationMismatch,
    ReasonRequired,
    VersionConflict,
)
from apps.fulfillment.idempotency import claim_command, complete_command
from apps.fulfillment.models import Fulfillment, FulfillmentItem, FulfillmentStatusHistory
from apps.fulfillment.transitions import ensure_transition
from apps.orders.models import Order, OrderItem
from apps.organizations.models import OrganizationUnit
from apps.platform.services import enqueue_event

QUANTITY_QUANTUM = Decimal("0.001")
DELIVERY_SNAPSHOT_FIELDS = {
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


def quantity(value):
    try:
        normalized = Decimal(str(value)).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidFulfillment("Quantidade inválida.") from exc
    if normalized <= 0:
        raise InvalidFulfillment("Quantidade deve ser positiva.")
    return normalized


def _require_permission(*, actor, organization, cancel=False):
    check = policies.can_cancel_fulfillments if cancel else policies.can_operate_fulfillments
    if actor is None or not check(user=actor, organization=organization):
        raise FulfillmentPermissionDenied("Membership ativa ou papel insuficiente.")


def _lock_order(*, organization, order):
    locked = Order.objects.select_for_update().filter(organization=organization, id=order.id).first()
    if locked is None:
        raise OrganizationMismatch("Pedido não pertence à organização.")
    if locked.status != Order.Status.CONFIRMED:
        raise InvalidFulfillment("Somente pedido confirmado e não cancelado pode ser atendido.")
    return locked


def _lock_fulfillment(*, organization, fulfillment):
    locked = (
        Fulfillment.objects.select_for_update()
        .select_related("order")
        .filter(organization=organization, id=fulfillment.id)
        .first()
    )
    if locked is None:
        raise OrganizationMismatch("Fulfillment não pertence à organização.")
    return locked


def _ensure_version(*, fulfillment, expected_version):
    if fulfillment.version != expected_version:
        raise VersionConflict(
            "Fulfillment alterado por outro usuário "
            f"(versão atual {fulfillment.version}, recebida {expected_version})."
        )


def _canonical_allocations(allocations):
    canonical = []
    seen = set()
    for allocation in allocations:
        item = allocation["order_item"]
        if item.id in seen:
            raise InvalidFulfillment("Um item do pedido não pode aparecer duas vezes no lote.")
        seen.add(item.id)
        canonical.append((item, quantity(allocation["quantity"])))
    if not canonical:
        raise InvalidFulfillment("Informe ao menos um item para o lote.")
    return sorted(canonical, key=lambda entry: str(entry[0].id))


def _lock_and_validate_allocations(*, organization, order, allocations, exclude_fulfillment=None):
    item_ids = [item.id for item, _ in allocations]
    locked_items = {
        item.id: item
        for item in OrderItem.objects.select_for_update()
        .filter(organization=organization, order=order, id__in=item_ids)
        .order_by("id")
    }
    if len(locked_items) != len(item_ids):
        raise OrganizationMismatch("Item não pertence ao pedido e à organização.")
    existing = FulfillmentItem.objects.select_for_update().filter(
        organization=organization,
        order_item_id__in=item_ids,
    ).exclude(fulfillment__status=Fulfillment.Status.CANCELLED)
    if exclude_fulfillment is not None:
        existing = existing.exclude(fulfillment=exclude_fulfillment)
    allocated = {}
    for existing_item in existing.order_by("id"):
        allocated[existing_item.order_item_id] = (
            allocated.get(existing_item.order_item_id, Decimal("0.000")) + existing_item.quantity
        )
    for item, requested in allocations:
        locked = locked_items[item.id]
        if allocated.get(item.id, Decimal("0.000")) + requested > locked.quantity:
            raise InvalidFulfillment(f"Quantidade alocada excede o item {locked.position} do pedido.")
    return [(locked_items[item.id], requested) for item, requested in allocations]


def _delivery_snapshot(order):
    snapshot = deepcopy(order.shipping_address_snapshot)
    if not snapshot or snapshot.get("schema_version") != 1 or set(snapshot) != DELIVERY_SNAPSHOT_FIELDS:
        raise InvalidFulfillment("Entrega exige endereço fechado e válido no pedido confirmado.")
    return snapshot


def _pickup_unit(*, organization, unit):
    locked = (
        OrganizationUnit.objects.select_for_update()
        .filter(organization=organization, id=getattr(unit, "id", None), is_active=True)
        .first()
    )
    if locked is None:
        raise OrganizationMismatch("Unidade de retirada não pertence à organização ou está inativa.")
    return locked


def _audit(*, fulfillment, actor, action, payload):
    record_event(
        organization=fulfillment.organization,
        actor=actor,
        action=action,
        entity_type="fulfillment",
        entity_id=fulfillment.id,
        payload={
            "fulfillment_number": fulfillment.display_number,
            "order_id": str(fulfillment.order_id),
            "status": fulfillment.status,
            "version": fulfillment.version,
            **payload,
        },
    )


def _outbox(*, fulfillment, event_type, command_id):
    enqueue_event(
        organization=fulfillment.organization,
        event_type=event_type,
        aggregate_type="fulfillment",
        aggregate_id=fulfillment.id,
        payload={
            "fulfillment_id": str(fulfillment.id),
            "order_id": str(fulfillment.order_id),
            "status": fulfillment.status,
            "method": fulfillment.method,
            "version": fulfillment.version,
        },
        idempotency_key=f"fulfillment:{fulfillment.id}:{event_type}:{command_id}",
    )


def _existing_result(receipt):
    result = Fulfillment.objects.filter(
        organization=receipt.organization,
        id=receipt.fulfillment_id,
    ).first()
    if result is None:
        raise IdempotencyConflict("O Fulfillment resultante deste comando não existe.")
    return result


@transaction.atomic
def create_fulfillment(
    *, organization, order, actor, method, allocations, idempotency_key, pickup_unit=None
):
    _require_permission(actor=actor, organization=organization)
    allocations = _canonical_allocations(allocations)
    payload = {
        "order_id": str(order.id),
        "method": method,
        "pickup_unit_id": str(pickup_unit.id) if pickup_unit else None,
        "allocations": [{"order_item_id": str(item.id), "quantity": str(value)} for item, value in allocations],
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="create_fulfillment",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)
    order = _lock_order(organization=organization, order=order)
    allocations = _lock_and_validate_allocations(
        organization=organization,
        order=order,
        allocations=allocations,
    )
    if method == Fulfillment.Method.DELIVERY:
        destination = _delivery_snapshot(order)
        unit = None
        unit_name = ""
    elif method == Fulfillment.Method.PICKUP:
        destination = {}
        unit = _pickup_unit(organization=organization, unit=pickup_unit)
        unit_name = unit.name
    else:
        raise InvalidFulfillment("Método de atendimento inválido.")
    sequence = (order.fulfillments.aggregate(value=Max("sequence"))["value"] or 0) + 1
    fulfillment = Fulfillment.objects.create(
        organization=organization,
        order=order,
        sequence=sequence,
        method=method,
        destination_snapshot=destination,
        pickup_unit=unit,
        pickup_unit_name_snapshot=unit_name,
        created_by=actor,
    )
    FulfillmentItem.objects.bulk_create(
        [
            FulfillmentItem(
                organization=organization,
                fulfillment=fulfillment,
                order_item=item,
                quantity=value,
            )
            for item, value in allocations
        ]
    )
    FulfillmentStatusHistory.objects.create(
        organization=organization,
        fulfillment=fulfillment,
        from_status="",
        to_status=Fulfillment.Status.DRAFT,
        actor=actor,
        command_id=str(idempotency_key),
    )
    _audit(fulfillment=fulfillment, actor=actor, action=FULFILLMENT_CREATED, payload={"item_count": len(allocations)})
    _outbox(fulfillment=fulfillment, event_type=FULFILLMENT_CREATED, command_id=idempotency_key)
    complete_command(receipt=receipt, fulfillment=fulfillment)
    return fulfillment


@transaction.atomic
def replace_allocations(
    *, organization, fulfillment, actor, allocations, expected_version, idempotency_key
):
    _require_permission(actor=actor, organization=organization)
    allocations = _canonical_allocations(allocations)
    payload = {
        "fulfillment_id": str(fulfillment.id),
        "expected_version": expected_version,
        "allocations": [{"order_item_id": str(item.id), "quantity": str(value)} for item, value in allocations],
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="replace_fulfillment_allocations",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)
    fulfillment = _lock_fulfillment(organization=organization, fulfillment=fulfillment)
    if fulfillment.status != Fulfillment.Status.DRAFT:
        raise InvalidFulfillment("Somente lote em rascunho pode ser editado.")
    _ensure_version(fulfillment=fulfillment, expected_version=expected_version)
    order = _lock_order(organization=organization, order=fulfillment.order)
    allocations = _lock_and_validate_allocations(
        organization=organization,
        order=order,
        allocations=allocations,
        exclude_fulfillment=fulfillment,
    )
    FulfillmentItem.objects.filter(fulfillment=fulfillment).delete()
    FulfillmentItem.objects.bulk_create(
        [
            FulfillmentItem(
                organization=organization,
                fulfillment=fulfillment,
                order_item=item,
                quantity=value,
            )
            for item, value in allocations
        ]
    )
    fulfillment.version += 1
    fulfillment.save(update_fields=("version", "updated_at"))
    _audit(fulfillment=fulfillment, actor=actor, action=FULFILLMENT_UPDATED, payload={"item_count": len(allocations)})
    _outbox(fulfillment=fulfillment, event_type=FULFILLMENT_UPDATED, command_id=idempotency_key)
    complete_command(receipt=receipt, fulfillment=fulfillment)
    return fulfillment


TRANSITION_EVENTS = {
    Fulfillment.Status.PREPARING: FULFILLMENT_PREPARING,
    Fulfillment.Status.READY: FULFILLMENT_READY,
    Fulfillment.Status.IN_TRANSIT: FULFILLMENT_DISPATCHED,
    Fulfillment.Status.COMPLETED: FULFILLMENT_COMPLETED,
    Fulfillment.Status.CANCELLED: FULFILLMENT_CANCELLED,
}
TIMESTAMP_FIELDS = {
    Fulfillment.Status.PREPARING: "preparing_at",
    Fulfillment.Status.READY: "ready_at",
    Fulfillment.Status.IN_TRANSIT: "dispatched_at",
    Fulfillment.Status.COMPLETED: "completed_at",
    Fulfillment.Status.CANCELLED: "cancelled_at",
}


@transaction.atomic
def transition_fulfillment(
    *,
    organization,
    fulfillment,
    actor,
    target_status,
    expected_version,
    idempotency_key,
    reason="",
):
    cancel = target_status == Fulfillment.Status.CANCELLED
    _require_permission(actor=actor, organization=organization, cancel=cancel)
    reason = reason.strip()
    if cancel and not reason:
        raise ReasonRequired("Cancelamento exige motivo.")
    if not cancel and reason:
        raise InvalidFulfillment("Motivo só deve ser informado no cancelamento.")
    payload = {
        "fulfillment_id": str(fulfillment.id),
        "target_status": target_status,
        "expected_version": expected_version,
        "reason": reason,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation=f"transition_fulfillment_{target_status}",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)
    fulfillment = _lock_fulfillment(organization=organization, fulfillment=fulfillment)
    _ensure_version(fulfillment=fulfillment, expected_version=expected_version)
    _lock_order(organization=organization, order=fulfillment.order)
    ensure_transition(fulfillment=fulfillment, target_status=target_status)
    from_status = fulfillment.status
    fulfillment.status = target_status
    fulfillment.version += 1
    timestamp_field = TIMESTAMP_FIELDS[target_status]
    setattr(fulfillment, timestamp_field, timezone.now())
    update_fields = ["status", "version", timestamp_field, "updated_at"]
    if cancel:
        fulfillment.cancel_reason = reason
        update_fields.append("cancel_reason")
    fulfillment.save(update_fields=update_fields)
    FulfillmentStatusHistory.objects.create(
        organization=organization,
        fulfillment=fulfillment,
        from_status=from_status,
        to_status=target_status,
        actor=actor,
        command_id=str(idempotency_key),
        reason_provided=bool(reason),
    )
    event_type = TRANSITION_EVENTS[target_status]
    _audit(fulfillment=fulfillment, actor=actor, action=event_type, payload={"from_status": from_status})
    _outbox(fulfillment=fulfillment, event_type=event_type, command_id=idempotency_key)
    complete_command(receipt=receipt, fulfillment=fulfillment)
    return fulfillment


@transaction.atomic
def cancel_from_order_event(*, organization, fulfillment, source_event_id):
    key = hashlib.sha256(f"{source_event_id}:{fulfillment.id}".encode()).hexdigest()
    payload = {"source_event_id": str(source_event_id), "fulfillment_id": str(fulfillment.id)}
    receipt, is_new = claim_command(
        organization=organization,
        operation="cancel_from_order_event",
        idempotency_key=key,
        payload=payload,
        source_event_id=source_event_id,
    )
    if not is_new:
        return _existing_result(receipt)
    fulfillment = _lock_fulfillment(organization=organization, fulfillment=fulfillment)
    if fulfillment.status in (Fulfillment.Status.COMPLETED, Fulfillment.Status.CANCELLED):
        complete_command(receipt=receipt, fulfillment=fulfillment)
        return fulfillment
    order = Order.objects.select_for_update().filter(organization=organization, id=fulfillment.order_id).first()
    if order is None:
        raise OrganizationMismatch("Pedido não pertence à organização.")
    if order.status != Order.Status.CANCELLED:
        raise InvalidFulfillment("Evento não corresponde a pedido cancelado.")
    from_status = fulfillment.status
    fulfillment.status = Fulfillment.Status.CANCELLED
    fulfillment.version += 1
    fulfillment.cancelled_at = timezone.now()
    fulfillment.cancel_reason = "Pedido cancelado"
    fulfillment.system_cancelled = True
    fulfillment.save(
        update_fields=(
            "status",
            "version",
            "cancelled_at",
            "cancel_reason",
            "system_cancelled",
            "updated_at",
        )
    )
    FulfillmentStatusHistory.objects.create(
        organization=organization,
        fulfillment=fulfillment,
        from_status=from_status,
        to_status=Fulfillment.Status.CANCELLED,
        command_id=key,
        reason_provided=True,
        system_generated=True,
    )
    _audit(
        fulfillment=fulfillment,
        actor=None,
        action=FULFILLMENT_CANCELLED,
        payload={"from_status": from_status, "system_generated": True},
    )
    _outbox(fulfillment=fulfillment, event_type=FULFILLMENT_CANCELLED, command_id=key)
    complete_command(receipt=receipt, fulfillment=fulfillment)
    return fulfillment


@transaction.atomic
def consume_order_cancelled_event(*, event):
    if event.event_type != "order.cancelled" or event.organization_id is None:
        raise InvalidFulfillment("Evento de cancelamento inválido.")
    order_id = event.payload.get("order_id")
    payload = {"source_event_id": str(event.id), "order_id": str(order_id)}
    receipt, is_new = claim_command(
        organization=event.organization,
        operation="consume_order_cancelled_event",
        idempotency_key=str(event.id),
        payload=payload,
        source_event_id=event.id,
    )
    if not is_new:
        return 0
    order = Order.objects.select_for_update().filter(
        organization=event.organization,
        id=order_id,
        status=Order.Status.CANCELLED,
    ).first()
    if order is None:
        raise InvalidFulfillment("Evento não corresponde a pedido cancelado da organização.")
    fulfillments = list(
        Fulfillment.objects.select_for_update()
        .filter(organization=event.organization, order=order)
        .order_by("id")
    )
    cancelled = 0
    for fulfillment in fulfillments:
        previous_status = fulfillment.status
        cancel_from_order_event(
            organization=event.organization,
            fulfillment=fulfillment,
            source_event_id=event.id,
        )
        if previous_status not in (Fulfillment.Status.COMPLETED, Fulfillment.Status.CANCELLED):
            cancelled += 1
    receipt.completed = True
    receipt.save(update_fields=("completed", "updated_at"))
    return cancelled
