from django.db.models import Q

from apps.fulfillment.models import Fulfillment
from apps.integrations.models import IntegrationConnection, IntegrationDelivery
from apps.messaging.models import Message
from apps.orders.models import Order
from apps.payments.models import PaymentIntent

DASHBOARD_LIMIT = 8
TIMELINE_LIMIT = 30


def dashboard_summary(*, organization):
    orders = Order.objects.filter(organization=organization, customer__organization=organization)
    payments = PaymentIntent.objects.filter(organization=organization, order__organization=organization)
    fulfillments = Fulfillment.objects.filter(organization=organization, order__organization=organization)
    messages = Message.objects.filter(
        organization=organization,
        customer__organization=organization,
        channel__organization=organization,
    )
    deliveries = IntegrationDelivery.objects.filter(
        organization=organization,
        connection__organization=organization,
        endpoint__organization=organization,
    )

    return {
        "open_orders": orders.filter(status=Order.Status.CONFIRMED).count(),
        "payment_attention": payments.filter(status=PaymentIntent.Status.REQUIRES_ATTENTION).count(),
        "fulfillment_open": fulfillments.filter(
            status__in=(
                Fulfillment.Status.DRAFT,
                Fulfillment.Status.PREPARING,
                Fulfillment.Status.READY,
                Fulfillment.Status.IN_TRANSIT,
            )
        ).count(),
        "message_attention": messages.filter(status__in=(Message.Status.FAILED, Message.Status.UNCERTAIN)).count(),
        "integration_attention": deliveries.filter(
            status__in=(IntegrationDelivery.Status.FAILED, IntegrationDelivery.Status.UNCERTAIN)
        ).count(),
    }


def payment_attention_for_organization(*, organization, limit=DASHBOARD_LIMIT):
    return PaymentIntent.objects.filter(
        organization=organization,
        order__organization=organization,
        status__in=(PaymentIntent.Status.REQUIRES_ATTENTION, PaymentIntent.Status.EXPIRED),
    ).select_related("order")[:limit]


def fulfillment_attention_for_organization(*, organization, limit=DASHBOARD_LIMIT):
    return Fulfillment.objects.filter(
        organization=organization,
        order__organization=organization,
        status__in=(
            Fulfillment.Status.DRAFT,
            Fulfillment.Status.PREPARING,
            Fulfillment.Status.READY,
            Fulfillment.Status.IN_TRANSIT,
        ),
    ).select_related("order")[:limit]


def message_attention_for_organization(*, organization, limit=DASHBOARD_LIMIT):
    return Message.objects.filter(
        organization=organization,
        customer__organization=organization,
        channel__organization=organization,
        status__in=(Message.Status.FAILED, Message.Status.UNCERTAIN),
    ).select_related("customer", "channel")[:limit]


def integration_attention_for_organization(*, organization, limit=DASHBOARD_LIMIT):
    connections = IntegrationConnection.objects.filter(
        organization=organization,
        status=IntegrationConnection.Status.DEGRADED,
    )[:limit]
    deliveries = IntegrationDelivery.objects.filter(
        organization=organization,
        connection__organization=organization,
        endpoint__organization=organization,
        status__in=(IntegrationDelivery.Status.FAILED, IntegrationDelivery.Status.UNCERTAIN),
    ).select_related("connection", "endpoint")[:limit]
    return {"connections": connections, "deliveries": deliveries}


def recent_orders_for_organization(*, organization, limit=DASHBOARD_LIMIT):
    return Order.objects.filter(
        organization=organization,
        customer__organization=organization,
    ).select_related("customer")[:limit]


def _status_label(choices, value):
    if not value:
        return "início"
    return dict(choices).get(value, value)


def _operational_timeline(*, organization, order, payment, fulfillments, messages):
    entries = []
    for row in order.status_history.filter(organization=organization).all():
        entries.append(
            {
                "at": row.created_at,
                "domain": "Pedido",
                "detail": (
                    f"{_status_label(Order.Status.choices, row.from_status)} → "
                    f"{_status_label(Order.Status.choices, row.to_status)}"
                ),
            }
        )

    if payment is not None:
        for row in payment.status_history.filter(organization=organization).all():
            entries.append(
                {
                    "at": row.created_at,
                    "domain": "Pagamento",
                    "detail": (
                        f"{_status_label(PaymentIntent.Status.choices, row.from_status)} → "
                        f"{_status_label(PaymentIntent.Status.choices, row.to_status)}"
                    ),
                }
            )

    for fulfillment in fulfillments:
        for row in fulfillment.status_history.filter(organization=organization).all():
            entries.append(
                {
                    "at": row.created_at,
                    "domain": fulfillment.display_number,
                    "detail": (
                        f"{_status_label(Fulfillment.Status.choices, row.from_status)} → "
                        f"{_status_label(Fulfillment.Status.choices, row.to_status)}"
                    ),
                }
            )

    for message in messages:
        for row in message.status_history.filter(organization=organization).all():
            entries.append(
                {
                    "at": row.created_at,
                    "domain": "Mensagem",
                    "detail": (
                        f"{_status_label(Message.Status.choices, row.from_status)} → "
                        f"{_status_label(Message.Status.choices, row.to_status)}"
                    ),
                }
            )

    entries.sort(key=lambda entry: entry["at"], reverse=True)
    return entries[:TIMELINE_LIMIT]


def order_workspace_for_organization(*, organization, order_id):
    order = (
        Order.objects.filter(
            organization=organization,
            customer__organization=organization,
            id=order_id,
        )
        .select_related("customer")
        .first()
    )
    if order is None:
        return None

    payment = PaymentIntent.objects.filter(
        organization=organization,
        order__organization=organization,
        order=order,
    ).first()
    fulfillments = list(
        Fulfillment.objects.filter(
            organization=organization,
            order__organization=organization,
            order=order,
        )
    )
    source_filter = Q(source_type=Message.SourceType.ORDER, source_id=order.id)
    if payment is not None:
        source_filter |= Q(source_type=Message.SourceType.PAYMENT, source_id=payment.id)
    fulfillment_ids = [fulfillment.id for fulfillment in fulfillments]
    if fulfillment_ids:
        source_filter |= Q(source_type=Message.SourceType.FULFILLMENT, source_id__in=fulfillment_ids)
    related_messages = list(
        Message.objects.filter(
            organization=organization,
            customer__organization=organization,
            channel__organization=organization,
        )
        .filter(source_filter)
        .select_related("channel")[:DASHBOARD_LIMIT]
    )
    return {
        "order": order,
        "payment": payment,
        "fulfillments": fulfillments,
        "messages": related_messages,
        "timeline": _operational_timeline(
            organization=organization,
            order=order,
            payment=payment,
            fulfillments=fulfillments,
            messages=related_messages,
        ),
    }


def dashboard_search_for_organization(*, organization, query, limit=DASHBOARD_LIMIT):
    query = (query or "").strip()
    if not query:
        return Order.objects.none()
    number_query = Q()
    if query.isdigit():
        number_query = Q(number=int(query))
    return (
        Order.objects.filter(
            organization=organization,
            customer__organization=organization,
        )
        .filter(number_query | Q(customer_name_snapshot__icontains=query))
        .select_related("customer")[:limit]
    )
