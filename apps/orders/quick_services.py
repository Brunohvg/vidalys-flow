import hashlib
from decimal import Decimal

from django.db import transaction

from apps.audit.services import record_event
from apps.customers import selectors as customer_selectors
from apps.customers import services as customer_services
from apps.customers.models import Customer
from apps.customers.normalization import normalize_document, normalize_email, normalize_phone
from apps.fulfillment import services as fulfillment_services
from apps.fulfillment.models import Fulfillment
from apps.orders import policies
from apps.orders import services as order_services
from apps.orders.events import ORDER_CREATED
from apps.orders.exceptions import OrderPermissionDenied
from apps.orders.idempotency import claim_command, complete_command
from apps.orders.models import Order, OrderStatusHistory
from apps.orders.numbering import allocate_order_number
from apps.platform.services import enqueue_event


def _require_permission(*, actor, organization):
    if not policies.can_manage_drafts(user=actor, organization=organization):
        raise OrderPermissionDenied("Membership ativa ou papel insuficiente.")


def _customer_type_for_document(document):
    normalized = normalize_document(document) if document else ""
    if len(normalized) == 14:
        return Customer.Type.COMPANY, normalized
    return Customer.Type.INDIVIDUAL, normalized


def _resolve_customer(
    *,
    organization,
    actor,
    customer=None,
    customer_name="",
    customer_document="",
    customer_phone="",
    customer_email="",
):
    if customer is not None:
        invalid_customer = (
            customer.organization_id != organization.id
            or customer.merged_into_id
            or customer.status != Customer.Status.ACTIVE
        )
        if invalid_customer:
            raise OrderPermissionDenied("Cliente inválido para a organização ativa.")
        return customer, False

    customer_type, normalized_document = _customer_type_for_document(customer_document)
    if normalized_document:
        existing = customer_selectors.find_by_document(
            organization=organization,
            document_normalized=normalized_document,
        )
        if existing and not existing.merged_into_id and existing.status == Customer.Status.ACTIVE:
            return existing, False

    display_name = customer_name.strip()
    if not display_name:
        raise ValueError("Informe o cliente ou o nome do novo cliente.")

    created = customer_services.create_customer(
        organization=organization,
        actor=actor,
        customer_type=customer_type,
        display_name=display_name,
        document=normalized_document,
        phone=customer_phone.strip(),
        email=customer_email.strip(),
    )
    return created, True


def _delivery_payload(
    *,
    has_delivery_address,
    delivery_postal_code,
    delivery_street,
    delivery_number,
    delivery_complement,
    delivery_district,
    delivery_city,
    delivery_state,
):
    if not has_delivery_address:
        return None
    return {
        "postal_code": delivery_postal_code.strip(),
        "street": delivery_street.strip(),
        "number": delivery_number.strip(),
        "complement": delivery_complement.strip(),
        "district": delivery_district.strip(),
        "city": delivery_city.strip(),
        "state": delivery_state.strip().upper(),
        "country": "BR",
    }


def _payload(
    *,
    customer,
    customer_name,
    customer_document,
    customer_phone,
    customer_email,
    channel,
    pricing_mode,
    manual_total,
    delivery_address,
):
    document = normalize_document(customer_document) if customer_document else ""
    phone = normalize_phone(customer_phone) if customer_phone else ""
    email = normalize_email(customer_email) if customer_email else ""
    return {
        "customer_id": str(customer.id) if customer else None,
        "customer_name": customer_name.strip(),
        "customer_document": document,
        "customer_phone": phone,
        "customer_email": email,
        "channel": channel.strip(),
        "pricing_mode": pricing_mode,
        "manual_total": str(manual_total) if manual_total is not None else None,
        "delivery_address": delivery_address,
    }


def _subkey(idempotency_key, step):
    return hashlib.sha256(f"quick-sale:{idempotency_key}:{step}".encode()).hexdigest()


@transaction.atomic
def create_quick_order(
    *,
    organization,
    actor,
    idempotency_key,
    customer=None,
    customer_name="",
    customer_document="",
    customer_phone="",
    customer_email="",
    channel="",
    pricing_mode=Order.PricingMode.MANUAL,
    manual_total=None,
    has_delivery_address=False,
    delivery_postal_code="",
    delivery_street="",
    delivery_number="",
    delivery_complement="",
    delivery_district="",
    delivery_city="",
    delivery_state="",
):
    """Create a draft Order and related inline Customer data in one transaction.

    The idempotency receipt is claimed before Customer or address creation so a
    retry cannot create duplicate inline data. Phone/e-mail are never used for
    silent identity resolution; reuse requires explicit customer selection or
    an exact canonical document match.
    """

    _require_permission(actor=actor, organization=organization)
    if pricing_mode not in Order.PricingMode.values:
        raise ValueError("Modo de preço inválido.")

    if pricing_mode == Order.PricingMode.MANUAL:
        if manual_total is None:
            raise ValueError("Informe o valor da venda.")
        manual_total = Decimal(manual_total).quantize(Decimal("0.01"))
        if manual_total <= 0:
            raise ValueError("O valor da venda deve ser maior que zero.")
    else:
        manual_total = None

    delivery_address = _delivery_payload(
        has_delivery_address=has_delivery_address,
        delivery_postal_code=delivery_postal_code,
        delivery_street=delivery_street,
        delivery_number=delivery_number,
        delivery_complement=delivery_complement,
        delivery_district=delivery_district,
        delivery_city=delivery_city,
        delivery_state=delivery_state,
    )
    payload = _payload(
        customer=customer,
        customer_name=customer_name,
        customer_document=customer_document,
        customer_phone=customer_phone,
        customer_email=customer_email,
        channel=channel,
        pricing_mode=pricing_mode,
        manual_total=manual_total,
        delivery_address=delivery_address,
    )
    receipt, is_new = claim_command(
        organization=organization,
        operation="create_quick_order",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        if receipt.order_id is None:
            raise ValueError("Comando idempotente incompleto; tente novamente.")
        return Order.objects.get(organization=organization, id=receipt.order_id)

    customer, inline_customer_created = _resolve_customer(
        organization=organization,
        actor=actor,
        customer=customer,
        customer_name=customer_name,
        customer_document=customer_document,
        customer_phone=customer_phone,
        customer_email=customer_email,
    )

    if delivery_address:
        customer_services.add_address(
            organization=organization,
            customer=customer,
            actor=actor,
            label="Entrega do pedido",
            recipient_name=customer.display_name,
            postal_code=delivery_address["postal_code"],
            street=delivery_address["street"],
            number=delivery_address["number"],
            complement=delivery_address["complement"],
            district=delivery_address["district"],
            city=delivery_address["city"],
            state=delivery_address["state"],
            country=delivery_address["country"],
            is_default_shipping=True,
        )

    number = allocate_order_number(organization=organization)
    values = {
        "organization": organization,
        "number": number,
        "customer": customer,
        "channel": channel.strip(),
        "pricing_mode": pricing_mode,
        "manual_total": manual_total,
        "created_by": actor,
    }
    if pricing_mode == Order.PricingMode.MANUAL:
        values.update(
            subtotal=manual_total,
            discount_total=Decimal("0.00"),
            surcharge_total=Decimal("0.00"),
            total=manual_total,
        )
    order = Order.objects.create(**values)

    OrderStatusHistory.objects.create(
        organization=organization,
        order=order,
        from_status="",
        to_status=Order.Status.DRAFT,
        actor=actor,
        command_id=str(idempotency_key),
    )
    record_event(
        organization=organization,
        actor=actor,
        action=ORDER_CREATED,
        entity_type="order",
        entity_id=order.id,
        payload={
            "order_number": order.display_number,
            "version": order.version,
            "status": order.status,
            "pricing_mode": order.pricing_mode,
            "inline_customer_created": inline_customer_created,
            "delivery_address_added": delivery_address is not None,
        },
    )
    enqueue_event(
        organization=organization,
        event_type=ORDER_CREATED,
        aggregate_type="order",
        aggregate_id=order.id,
        payload={
            "order_id": str(order.id),
            "order_number": order.display_number,
            "status": order.status,
            "version": order.version,
        },
        idempotency_key=f"order:{order.id}:{ORDER_CREATED}:{idempotency_key}",
    )
    complete_command(receipt=receipt, order=order)
    return order


@transaction.atomic
def create_quick_sale(
    *,
    organization,
    actor,
    idempotency_key,
    fulfillment_method,
    pickup_unit=None,
    product=None,
    product_quantity=None,
    product_unit_price=None,
    customer=None,
    customer_name="",
    customer_document="",
    customer_phone="",
    customer_email="",
    channel="",
    pricing_mode=Order.PricingMode.MANUAL,
    manual_total=None,
    has_delivery_address=False,
    delivery_postal_code="",
    delivery_street="",
    delivery_number="",
    delivery_complement="",
    delivery_district="",
    delivery_city="",
    delivery_state="",
):
    """Register the common sale path without introducing a parallel lifecycle.

    Order creation, optional item creation, Order confirmation and Fulfillment
    creation delegate to their canonical services inside one transaction. The
    derived idempotency keys make a successful retry return the same aggregate
    results instead of duplicating Customer, OrderItem or Fulfillment rows.
    """

    if fulfillment_method not in Fulfillment.Method.values:
        raise ValueError("Método de atendimento inválido.")
    if fulfillment_method == Fulfillment.Method.DELIVERY and not has_delivery_address:
        raise ValueError("Entrega exige endereço completo.")
    if fulfillment_method == Fulfillment.Method.PICKUP and has_delivery_address:
        raise ValueError("Retirada não utiliza endereço de entrega.")
    if fulfillment_method == Fulfillment.Method.PICKUP and pickup_unit is None:
        raise ValueError("Retirada exige unidade ativa.")
    if fulfillment_method == Fulfillment.Method.DELIVERY and pickup_unit is not None:
        raise ValueError("Entrega não utiliza unidade de retirada.")
    if pricing_mode == Order.PricingMode.ITEMIZED and product is None:
        raise ValueError("Venda por itens exige ao menos um produto.")
    if product is not None and (product_quantity is None or product_unit_price is None):
        raise ValueError("Produto exige quantidade e preço unitário.")

    order = create_quick_order(
        organization=organization,
        actor=actor,
        idempotency_key=_subkey(idempotency_key, "order"),
        customer=customer,
        customer_name=customer_name,
        customer_document=customer_document,
        customer_phone=customer_phone,
        customer_email=customer_email,
        channel=channel,
        pricing_mode=pricing_mode,
        manual_total=manual_total,
        has_delivery_address=has_delivery_address,
        delivery_postal_code=delivery_postal_code,
        delivery_street=delivery_street,
        delivery_number=delivery_number,
        delivery_complement=delivery_complement,
        delivery_district=delivery_district,
        delivery_city=delivery_city,
        delivery_state=delivery_state,
    )

    item = None
    if product is not None:
        item = order_services.add_item(
            organization=organization,
            order=order,
            actor=actor,
            expected_version=1,
            idempotency_key=_subkey(idempotency_key, "item"),
            product=product,
            quantity=product_quantity,
            unit_price=product_unit_price,
        )

    expected_confirmation_version = 2 if product is not None else 1
    order = order_services.confirm_order(
        organization=organization,
        order=order,
        actor=actor,
        expected_version=expected_confirmation_version,
        idempotency_key=_subkey(idempotency_key, "confirm"),
    )
    allocations = []
    if item is not None:
        allocations.append({"order_item": item, "quantity": item.quantity})
    fulfillment = fulfillment_services.create_fulfillment(
        organization=organization,
        order=order,
        actor=actor,
        method=fulfillment_method,
        allocations=allocations,
        pickup_unit=pickup_unit,
        idempotency_key=_subkey(idempotency_key, "fulfillment"),
    )
    return order, fulfillment
