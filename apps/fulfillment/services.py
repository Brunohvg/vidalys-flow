from decimal import Decimal

from django.db import transaction, models
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_event
from apps.platform.services import enqueue_event
from apps.fulfillment.idempotency import claim_command, complete_command
from apps.fulfillment.exceptions import OrganizationMismatch, QuantityExceeded, IdempotencyConflict


def _require_order_belongs(organization, order):
    if order.organization_id != organization.id:
        raise OrganizationMismatch("Pedido não pertence à organização.")


def _lock_order(order, organization):
    locked = Fulfillment.objects.model._meta.apps.get_model("orders", "Order").objects.select_for_update().filter(
        organization=organization, id=order.id
    ).first()
    if not locked:
        raise OrganizationMismatch("Pedido não pertence à organização.")
    return locked


def _existing_result(receipt):
    from apps.fulfillment.models import Fulfillment

    if receipt.fulfillment_id:
        result = Fulfillment.objects.filter(organization=receipt.organization, id=receipt.fulfillment_id).first()
        if result is None:
            raise IdempotencyConflict("O fulfillment resultante deste comando não existe mais.")
        return result
    raise IdempotencyConflict("Comando idempotente não tem resultado registrado.")


@transaction.atomic
def create_fulfillment(
    *, organization, order, actor, method, allocations, idempotency_key, pickup_unit=None, destination_snapshot=None
):
    """Create a fulfillment batch allocating quantities from confirmed order items.

    `allocations` is a list of dicts: [{"order_item_id": <uuid>, "quantity": Decimal/str}, ...]
    """
    payload = {
        "order_id": str(order.id),
        "method": method,
        "allocations": [
            {"order_item_id": str(a["order_item_id"]), "quantity": str(a["quantity"])} for a in allocations
        ],
    }
    receipt, is_new = claim_command(
        organization=organization, operation="create_fulfillment", idempotency_key=idempotency_key, payload=payload, actor=actor
    )
    if not is_new:
        return _existing_result(receipt)

    # lock order and its items
    from apps.fulfillment.models import Fulfillment, FulfillmentItem, FulfillmentStatusHistory

    Order = Fulfillment.objects.model._meta.apps.get_model("orders", "Order")
    OrderItem = Fulfillment.objects.model._meta.apps.get_model("orders", "OrderItem")
    order_locked = Order.objects.select_for_update().filter(organization=organization, id=order.id).first()
    if not order_locked:
        raise OrganizationMismatch("Pedido não pertence à organização.")
    if order_locked.status != Order.Status.CONFIRMED:
        raise OrganizationMismatch("Somente pedidos confirmados podem gerar fulfillments.")

    item_ids = [a["order_item_id"] for a in allocations]
    items = list(OrderItem.objects.select_for_update().filter(organization=organization, order=order_locked, id__in=item_ids))
    items_map = {str(i.id): i for i in items}
    if len(items_map) != len(item_ids):
        raise OrganizationMismatch("Um ou mais itens não pertencem ao pedido/organização.")

    # calculate existing allocations per order_item
    non_cancelled_statuses = [s for s, _ in Fulfillment.Status.choices if s != Fulfillment.Status.CANCELLED]
    allocated = (
        FulfillmentItem.objects.filter(order_item_id__in=item_ids, fulfillment__status__in=non_cancelled_statuses)
        .values("order_item")
        .annotate(total=models.Sum("quantity"))
    )
    allocated_map = {str(a["order_item"]): Decimal(str(a["total"])) for a in allocated}

    # validate allocations
    for a in allocations:
        item = items_map.get(str(a["order_item_id"]))
        q = Decimal(str(a["quantity"]))
        if q <= 0:
            raise QuantityExceeded("Quantidade deve ser positiva.")
        already = allocated_map.get(str(item.id), Decimal("0"))
        if already + q > item.quantity:
            raise QuantityExceeded("A soma das alocações excede a quantidade confirmada do item.")

    # sequence allocation
    seq = (Fulfillment.objects.filter(organization=organization, order=order_locked).aggregate(value=Max("sequence"))["value"] or 0) + 1

    fulfillment = Fulfillment.objects.create(
        organization=organization,
        order=order_locked,
        sequence=seq,
        method=method,
        destination_snapshot=destination_snapshot or {},
        pickup_unit=pickup_unit,
        pickup_unit_name_snapshot=(getattr(pickup_unit, "name", "") if pickup_unit else ""),
        created_by=actor,
    )

    for a in allocations:
        item = items_map[str(a["order_item_id"])]
        FulfillmentItem.objects.create(
            organization=organization,
            fulfillment=fulfillment,
            order_item=item,
            quantity=Decimal(str(a["quantity"])),
        )

    FulfillmentStatusHistory.objects.create(
        organization=organization,
        fulfillment=fulfillment,
        from_status="",
        to_status=Fulfillment.Status.DRAFT,
        actor=actor,
        command_id=str(idempotency_key),
        system_generated=False,
    )

    record_event(
        organization=organization,
        actor=actor,
        action="fulfillment.created",
        entity_type="fulfillment",
        entity_id=fulfillment.id,
        payload={"order_id": str(order_locked.id), "sequence": fulfillment.sequence},
    )
    enqueue_event(
        organization=organization,
        event_type="fulfillment.created",
        aggregate_type="fulfillment",
        aggregate_id=fulfillment.id,
        payload={"fulfillment_id": str(fulfillment.id), "order_id": str(order_locked.id)},
        idempotency_key=f"fulfillment:{fulfillment.id}:created:{idempotency_key}",
    )

    complete_command(receipt=receipt, fulfillment=fulfillment)
    return fulfillment
