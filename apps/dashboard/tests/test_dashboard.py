from decimal import Decimal

import pytest
from django.apps import apps
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import ContactPoint, Customer
from apps.fulfillment.models import Fulfillment
from apps.integrations.models import IntegrationConnection, IntegrationDelivery, IntegrationEndpoint
from apps.messaging.models import Message, MessageTemplate, MessagingChannel, MessagingProviderConnection
from apps.orders.models import Order
from apps.payments.models import PaymentIntent

from ..selectors import (
    dashboard_search_for_organization,
    dashboard_summary,
    fulfillment_attention_for_organization,
    integration_attention_for_organization,
    message_attention_for_organization,
    order_workspace_for_organization,
    payment_attention_for_organization,
    recent_orders_for_organization,
)


def _customer(*, organization, name):
    return Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name=name,
    )


def _confirmed_order(*, organization, customer, user, number, name):
    return Order.objects.create(
        organization=organization,
        number=number,
        customer=customer,
        status=Order.Status.CONFIRMED,
        channel="whatsapp",
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        customer_name_snapshot=name,
        created_by=user,
        confirmed_at=timezone.now(),
    )


def _failed_message(*, organization, customer, channel, order, user, suffix):
    template = MessageTemplate.objects.create(
        organization=organization,
        semantic_key=f"dashboard-{suffix}",
        name=f"Dashboard {suffix}",
        channel=MessageTemplate.Channel.WHATSAPP,
        body_text="Teste",
    )
    contact = ContactPoint.objects.create(
        customer=customer,
        kind=ContactPoint.Kind.WHATSAPP,
        value=f"+5500000000{suffix}",
        normalized_value=f"5500000000{suffix}",
        is_primary=True,
    )
    return Message.objects.create(
        organization=organization,
        source_type=Message.SourceType.ORDER,
        source_id=order.id,
        source_version=order.version,
        purpose="dashboard_attention",
        template=template,
        template_semantic_key=template.semantic_key,
        template_version=template.version,
        channel=channel,
        channel_kind=MessagingChannel.Kind.WHATSAPP,
        locale="pt-BR",
        customer=customer,
        customer_display_name=customer.display_name,
        contact_point=contact,
        destination_snapshot=contact.value,
        status=Message.Status.FAILED,
        failed_at=timezone.now(),
        created_by=user,
    )


@pytest.mark.django_db
def test_dashboard_summary_and_search_are_organization_scoped(
    organization,
    other_organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente A")
    other_customer = _customer(organization=other_organization, name="Cliente B")
    order = _confirmed_order(
        organization=organization,
        customer=customer,
        user=user,
        number=101,
        name="Cliente A",
    )
    other_order = _confirmed_order(
        organization=other_organization,
        customer=other_customer,
        user=user,
        number=202,
        name="Cliente B",
    )
    PaymentIntent.objects.create(
        organization=organization,
        order=order,
        status=PaymentIntent.Status.REQUIRES_ATTENTION,
        amount=Decimal("10.00"),
        order_number_snapshot=order.display_number,
        customer_name_snapshot="Cliente A",
        created_by=user,
        attention_code="manual_review",
    )
    PaymentIntent.objects.create(
        organization=other_organization,
        order=other_order,
        status=PaymentIntent.Status.REQUIRES_ATTENTION,
        amount=Decimal("10.00"),
        order_number_snapshot=other_order.display_number,
        customer_name_snapshot="Cliente B",
        created_by=user,
        attention_code="manual_review",
    )
    Fulfillment.objects.create(
        organization=organization,
        order=order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        created_by=user,
    )
    Fulfillment.objects.create(
        organization=other_organization,
        order=other_order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        created_by=user,
    )

    summary = dashboard_summary(organization=organization)
    assert summary == {
        "open_orders": 1,
        "payment_attention": 1,
        "fulfillment_open": 1,
        "message_attention": 0,
        "integration_attention": 0,
    }
    assert list(dashboard_search_for_organization(organization=organization, query="101")) == [order]
    assert list(dashboard_search_for_organization(organization=organization, query="Cliente B")) == []


@pytest.mark.django_db
def test_recent_orders_keeps_customer_reads_in_one_query(
    django_assert_num_queries,
    organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente A")
    for number in range(1, 6):
        _confirmed_order(
            organization=organization,
            customer=customer,
            user=user,
            number=number,
            name="Cliente A",
        )

    with django_assert_num_queries(1):
        rows = list(recent_orders_for_organization(organization=organization))
        assert [row.customer.display_name for row in rows] == ["Cliente A"] * 5


@pytest.mark.django_db
def test_order_workspace_composes_only_active_organization(
    organization,
    other_organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente A")
    other_customer = _customer(organization=other_organization, name="Cliente B")
    order = _confirmed_order(
        organization=organization,
        customer=customer,
        user=user,
        number=1,
        name="Cliente A",
    )
    other_order = _confirmed_order(
        organization=other_organization,
        customer=other_customer,
        user=user,
        number=2,
        name="Cliente B",
    )
    payment = PaymentIntent.objects.create(
        organization=organization,
        order=order,
        status=PaymentIntent.Status.PENDING,
        amount=Decimal("10.00"),
        order_number_snapshot=order.display_number,
        customer_name_snapshot="Cliente A",
        created_by=user,
    )
    fulfillment = Fulfillment.objects.create(
        organization=organization,
        order=order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        created_by=user,
    )

    workspace = order_workspace_for_organization(organization=organization, order_id=order.id)
    assert workspace["order"] == order
    assert workspace["payment"] == payment
    assert list(workspace["fulfillments"]) == [fulfillment]
    assert list(workspace["messages"]) == []
    assert order_workspace_for_organization(organization=organization, order_id=other_order.id) is None


@pytest.mark.django_db
def test_order_workspace_rejects_cross_organization_related_records(
    organization,
    other_organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente A")
    order = _confirmed_order(
        organization=organization,
        customer=customer,
        user=user,
        number=3,
        name="Cliente A",
    )
    PaymentIntent.objects.create(
        organization=other_organization,
        order=order,
        status=PaymentIntent.Status.PENDING,
        amount=Decimal("10.00"),
        order_number_snapshot=order.display_number,
        customer_name_snapshot="Cliente A",
        created_by=user,
    )
    Fulfillment.objects.create(
        organization=other_organization,
        order=order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        created_by=user,
    )

    workspace = order_workspace_for_organization(organization=organization, order_id=order.id)

    assert workspace["order"] == order
    assert workspace["payment"] is None
    assert list(workspace["fulfillments"]) == []


@pytest.mark.django_db
def test_attention_queues_reject_cross_organization_order_relations(
    organization,
    other_organization,
    user,
    operator_membership,
):
    other_customer = _customer(organization=other_organization, name="Cliente B")
    other_order = _confirmed_order(
        organization=other_organization,
        customer=other_customer,
        user=user,
        number=901,
        name="Cliente B",
    )
    PaymentIntent.objects.create(
        organization=organization,
        order=other_order,
        status=PaymentIntent.Status.REQUIRES_ATTENTION,
        amount=Decimal("10.00"),
        order_number_snapshot=other_order.display_number,
        customer_name_snapshot="Cliente B",
        created_by=user,
        attention_code="manual_review",
    )
    Fulfillment.objects.create(
        organization=organization,
        order=other_order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        created_by=user,
    )

    assert list(payment_attention_for_organization(organization=organization)) == []
    assert list(fulfillment_attention_for_organization(organization=organization)) == []


@pytest.mark.django_db
def test_order_reads_reject_cross_organization_customer_relation(
    organization,
    other_organization,
    user,
    operator_membership,
):
    other_customer = _customer(organization=other_organization, name="Cliente B")
    malformed_order = _confirmed_order(
        organization=organization,
        customer=other_customer,
        user=user,
        number=902,
        name="",
    )

    assert list(recent_orders_for_organization(organization=organization)) == []
    assert list(dashboard_search_for_organization(organization=organization, query="902")) == []
    assert order_workspace_for_organization(organization=organization, order_id=malformed_order.id) is None


@pytest.mark.django_db
def test_message_attention_rejects_cross_organization_customer_and_channel(
    organization,
    other_organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente A")
    other_customer = _customer(organization=other_organization, name="Cliente B")
    order = _confirmed_order(
        organization=organization,
        customer=customer,
        user=user,
        number=903,
        name="Cliente A",
    )
    connection = MessagingProviderConnection.objects.create(
        organization=other_organization,
        provider=MessagingProviderConnection.Provider.EVOLUTION,
        mode=MessagingProviderConnection.Mode.LINKED_DEVICE,
        display_name="Canal externo",
    )
    channel = MessagingChannel.objects.create(
        organization=other_organization,
        connection=connection,
        kind=MessagingChannel.Kind.WHATSAPP,
        display_name="WhatsApp B",
    )
    _failed_message(
        organization=organization,
        customer=other_customer,
        channel=channel,
        order=order,
        user=user,
        suffix="903",
    )

    assert list(message_attention_for_organization(organization=organization)) == []
    assert dashboard_summary(organization=organization)["message_attention"] == 0


@pytest.mark.django_db
def test_integration_attention_rejects_cross_organization_related_records(
    organization,
    other_organization,
    operator_membership,
):
    connection = IntegrationConnection.objects.create(
        organization=other_organization,
        key="external-b",
        status=IntegrationConnection.Status.ACTIVE,
    )
    endpoint = IntegrationEndpoint.objects.create(
        organization=other_organization,
        connection=connection,
        key="orders",
        direction=IntegrationEndpoint.Direction.EGRESS,
        is_active=True,
    )
    IntegrationDelivery.objects.create(
        organization=organization,
        connection=connection,
        endpoint=endpoint,
        source_type="order",
        source_id="cross-tenant",
        source_version=1,
        contract_version=1,
        operation_key="sync-order",
        idempotency_key="cross-tenant-delivery",
        payload_digest="0" * 64,
        status=IntegrationDelivery.Status.FAILED,
    )

    attention = integration_attention_for_organization(organization=organization)
    assert list(attention["deliveries"]) == []
    assert dashboard_summary(organization=organization)["integration_attention"] == 0


@pytest.mark.django_db
def test_dashboard_views_are_read_only_and_cross_org_workspace_is_404(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    other_customer = _customer(organization=other_organization, name="Cliente B")
    other_order = _confirmed_order(
        organization=other_organization,
        customer=other_customer,
        user=user,
        number=2,
        name="Cliente B",
    )
    client.force_login(user)

    home = client.get(reverse("dashboard:home"))
    assert home.status_code == 200
    assert "visão operacional consolidada" in home.content.decode()
    assert client.post(reverse("dashboard:home"), {}).status_code == 405
    assert client.get(reverse("dashboard:order-workspace", args=[other_order.id])).status_code == 404
    assert client.post(reverse("dashboard:order-workspace", args=[other_order.id]), {}).status_code == 405


def test_dashboard_app_has_no_persistence_models():
    assert list(apps.get_app_config("dashboard").get_models()) == []
