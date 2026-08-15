from datetime import date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.dashboard.reports import order_report_for_organization, report_range
from apps.orders.models import Order

pytestmark = pytest.mark.django_db


def _customer(*, organization, name):
    return Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name=name,
    )


def _order(*, organization, customer, user, number, total, day):
    order = Order.objects.create(
        organization=organization,
        number=number,
        customer=customer,
        status=Order.Status.CONFIRMED,
        subtotal=Decimal(total),
        total=Decimal(total),
        customer_name_snapshot=customer.display_name,
        created_by=user,
        confirmed_at=timezone.now(),
    )
    stamp = timezone.make_aware(datetime(day.year, day.month, day.day, 12, 0))
    Order.objects.filter(pk=order.pk).update(created_at=stamp)
    order.created_at = stamp
    return order


def test_custom_report_range_is_inclusive_and_invalid_values_fall_back_to_month():
    period, start, end = report_range(
        period="custom",
        custom_start="2026-08-10",
        custom_end="2026-08-12",
        today=date(2026, 8, 15),
    )
    assert period == "custom"
    assert start.date() == date(2026, 8, 10)
    assert end.date() == date(2026, 8, 13)

    period, start, end = report_range(
        period="custom",
        custom_start="2026-08-20",
        custom_end="2026-08-10",
        today=date(2026, 8, 15),
    )
    assert period == "month"
    assert start.date() == date(2026, 8, 1)
    assert end.date() == date(2026, 9, 1)

    period, start, end = report_range(
        period="custom",
        custom_start="inválida",
        custom_end="2026-08-10",
        today=date(2026, 8, 15),
    )
    assert period == "month"
    assert start.date() == date(2026, 8, 1)
    assert end.date() == date(2026, 9, 1)


def test_custom_report_scopes_organization_and_compares_equal_duration(
    organization,
    other_organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente Relatório")
    hidden_customer = _customer(organization=other_organization, name="Cliente Oculto")
    _order(
        organization=organization,
        customer=customer,
        user=user,
        number=1,
        total="30.00",
        day=date(2026, 8, 10),
    )
    _order(
        organization=organization,
        customer=customer,
        user=user,
        number=2,
        total="20.00",
        day=date(2026, 8, 12),
    )
    _order(
        organization=organization,
        customer=customer,
        user=user,
        number=3,
        total="7.00",
        day=date(2026, 8, 8),
    )
    _order(
        organization=other_organization,
        customer=hidden_customer,
        user=user,
        number=4,
        total="999.00",
        day=date(2026, 8, 11),
    )

    report = order_report_for_organization(
        organization=organization,
        period="custom",
        custom_start="2026-08-10",
        custom_end="2026-08-12",
    )

    assert report["period"] == "custom"
    assert report["start_date"] == date(2026, 8, 10)
    assert report["end_date"] == date(2026, 8, 12)
    assert report["all"]["count"] == 2
    assert report["all"]["value"] == Decimal("50.00")
    assert report["previous"]["start"].date() == date(2026, 8, 7)
    assert report["previous"]["end"].date() == date(2026, 8, 10)
    assert report["previous"]["all"]["count"] == 1
    assert report["previous"]["all"]["value"] == Decimal("7.00")


def test_custom_report_view_and_csv_use_same_range(
    client,
    organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente CSV personalizado")
    _order(
        organization=organization,
        customer=customer,
        user=user,
        number=10,
        total="42.00",
        day=date(2026, 8, 10),
    )
    _order(
        organization=organization,
        customer=customer,
        user=user,
        number=11,
        total="99.00",
        day=date(2026, 8, 20),
    )
    client.force_login(user)
    params = {"period": "custom", "start": "2026-08-10", "end": "2026-08-12"}

    page = client.get(reverse("dashboard:order-report"), params)
    export = client.get(reverse("dashboard:order-report-csv"), params)
    html = page.content.decode()
    csv_text = export.content.decode("utf-8-sig")

    assert page.status_code == 200
    assert "Personalizado" in html
    assert 'value="2026-08-10"' in html
    assert 'value="2026-08-12"' in html
    assert "42.00" in csv_text
    assert "99.00" not in csv_text
