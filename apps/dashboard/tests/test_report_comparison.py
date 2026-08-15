from datetime import date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.dashboard.reports import order_report_for_organization
from apps.orders.models import Order
from apps.organizations.selectors import ACTIVE_ORGANIZATION_SESSION_KEY

pytestmark = pytest.mark.django_db


def _customer(*, organization, name):
    return Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name=name,
    )


def _confirmed_order(*, organization, customer, user, number, total, created_day):
    stamp = timezone.make_aware(datetime.combine(created_day, datetime.min.time()))
    order = Order.objects.create(
        organization=organization,
        number=number,
        customer=customer,
        status=Order.Status.CONFIRMED,
        subtotal=Decimal(total),
        total=Decimal(total),
        customer_name_snapshot=customer.display_name,
        created_by=user,
        confirmed_at=stamp,
    )
    Order.objects.filter(pk=order.pk).update(created_at=stamp)
    return order


def _activate_organization(client, organization):
    session = client.session
    session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(organization.id)
    session.save()


def test_report_compares_same_duration_previous_period_and_keeps_organization_scope(
    organization,
    other_organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente atual")
    hidden_customer = _customer(organization=other_organization, name="Cliente oculto")
    _confirmed_order(
        organization=organization,
        customer=customer,
        user=user,
        number=1,
        total="30.00",
        created_day=date(2026, 8, 15),
    )
    _confirmed_order(
        organization=organization,
        customer=customer,
        user=user,
        number=2,
        total="20.00",
        created_day=date(2026, 8, 14),
    )
    _confirmed_order(
        organization=other_organization,
        customer=hidden_customer,
        user=user,
        number=3,
        total="999.00",
        created_day=date(2026, 8, 14),
    )

    report = order_report_for_organization(
        organization=organization,
        period="today",
        today=date(2026, 8, 15),
    )

    assert report["all"]["value"] == Decimal("30.00")
    assert report["previous"]["start"].date() == date(2026, 8, 14)
    assert report["previous"]["end"].date() == date(2026, 8, 15)
    assert report["previous"]["all"] == {
        "count": 1,
        "value": Decimal("20.00"),
        "ticket": Decimal("20.00"),
    }
    assert report["previous"]["confirmed"]["count"] == 1


def test_report_page_renders_previous_period_comparison(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    _activate_organization(client, organization)

    response = client.get(reverse("dashboard:order-report"), {"period": "today"})

    assert response.status_code == 200
    html = response.content.decode()
    assert "Comparação com o período anterior" in html
    assert "Pedidos no período anterior" in html
