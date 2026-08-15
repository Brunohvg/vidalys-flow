from decimal import Decimal

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.dashboard.selectors import order_workspace_for_organization
from apps.fulfillment.models import Fulfillment, FulfillmentStatusHistory
from apps.orders.models import Order, OrderStatusHistory
from apps.payments.models import PaymentIntent, PaymentStatusHistory


@pytest.mark.django_db
def test_order_workspace_timeline_combines_canonical_histories_without_payloads(
    organization,
    user,
    operator_membership,
):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente Timeline",
    )
    order = Order.objects.create(
        organization=organization,
        number=901,
        customer=customer,
        status=Order.Status.CONFIRMED,
        subtotal=Decimal("25.00"),
        total=Decimal("25.00"),
        customer_name_snapshot=customer.display_name,
        created_by=user,
        confirmed_at=timezone.now(),
    )
    OrderStatusHistory.objects.create(
        organization=organization,
        order=order,
        from_status=Order.Status.DRAFT,
        to_status=Order.Status.CONFIRMED,
        actor=user,
        command_id="order-secret-command",
    )
    payment = PaymentIntent.objects.create(
        organization=organization,
        order=order,
        amount=Decimal("25.00"),
        order_number_snapshot=order.display_number,
        customer_name_snapshot=customer.display_name,
        created_by=user,
    )
    PaymentStatusHistory.objects.create(
        organization=organization,
        intent=payment,
        from_status="",
        to_status=PaymentIntent.Status.PENDING,
        actor=user,
        command_id="payment-secret-command",
        source="command",
    )
    fulfillment = Fulfillment.objects.create(
        organization=organization,
        order=order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        destination_snapshot={},
        created_by=user,
    )
    FulfillmentStatusHistory.objects.create(
        organization=organization,
        fulfillment=fulfillment,
        from_status="",
        to_status=Fulfillment.Status.DRAFT,
        actor=user,
        command_id="fulfillment-secret-command",
    )

    workspace = order_workspace_for_organization(organization=organization, order_id=order.id)

    assert workspace is not None
    domains = {entry["domain"] for entry in workspace["timeline"]}
    assert {"Pedido", "Pagamento", fulfillment.display_number}.issubset(domains)
    assert all(set(entry) == {"at", "domain", "detail"} for entry in workspace["timeline"])
    rendered = " ".join(entry["detail"] for entry in workspace["timeline"])
    assert "secret-command" not in rendered
