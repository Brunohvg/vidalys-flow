from decimal import Decimal

import pytest
from django.apps import apps
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.fulfillment.models import Fulfillment
from apps.orders.models import Order
from apps.payments.models import PaymentIntent

from ..selectors import (
    dashboard_search_for_organization,
    dashboard_summary,
    order_workspace_for_organization,
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
