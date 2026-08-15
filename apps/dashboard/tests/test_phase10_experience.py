from datetime import date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.dashboard.pickups import ready_pickups_for_organization
from apps.dashboard.reports import order_report_for_organization, report_range
from apps.fulfillment.models import Fulfillment
from apps.orders.models import Order
from apps.organizations.models import OrganizationUnit

pytestmark = pytest.mark.django_db


def _customer(*, organization, name):
    return Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name=name,
    )


def _order(*, organization, customer, user, number, status=Order.Status.CONFIRMED, total="10.00"):
    return Order.objects.create(
        organization=organization,
        number=number,
        customer=customer,
        status=status,
        subtotal=Decimal(total),
        total=Decimal(total),
        customer_name_snapshot=customer.display_name,
        created_by=user,
        confirmed_at=timezone.now() if status == Order.Status.CONFIRMED else None,
    )


def _set_created(order, *, year, month, day):
    stamp = timezone.make_aware(datetime(year, month, day, 12, 0))
    Order.objects.filter(pk=order.pk).update(created_at=stamp)
    order.created_at = stamp


def test_report_range_covers_supported_periods():
    today = date(2026, 8, 15)

    period, start, end = report_range(period="today", today=today)
    assert period == "today"
    assert start.date() == date(2026, 8, 15)
    assert end.date() == date(2026, 8, 16)

    period, start, end = report_range(period="yesterday", today=today)
    assert period == "yesterday"
    assert start.date() == date(2026, 8, 14)
    assert end.date() == date(2026, 8, 15)

    period, start, end = report_range(period="7d", today=today)
    assert period == "7d"
    assert start.date() == date(2026, 8, 9)
    assert end.date() == date(2026, 8, 16)

    period, start, end = report_range(period="previous_month", today=today)
    assert period == "previous_month"
    assert start.date() == date(2026, 7, 1)
    assert end.date() == date(2026, 8, 1)

    period, start, end = report_range(period="year", today=today)
    assert period == "year"
    assert start.date() == date(2026, 1, 1)
    assert end.date() == date(2027, 1, 1)

    period, start, end = report_range(period="unknown", today=today)
    assert period == "month"
    assert start.date() == date(2026, 8, 1)
    assert end.date() == date(2026, 9, 1)

    _, _, december_end = report_range(period="month", today=date(2026, 12, 20))
    assert december_end.date() == date(2027, 1, 1)


def test_order_report_is_scoped_and_calculates_status_totals(
    organization,
    other_organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente Relatório")
    other_customer = _customer(organization=other_organization, name="Oculto")
    confirmed = _order(
        organization=organization,
        customer=customer,
        user=user,
        number=1,
        total="30.00",
    )
    draft = _order(
        organization=organization,
        customer=customer,
        user=user,
        number=2,
        status=Order.Status.DRAFT,
        total="10.00",
    )
    cancelled = _order(
        organization=organization,
        customer=customer,
        user=user,
        number=3,
        status=Order.Status.CANCELLED,
        total="20.00",
    )
    hidden = _order(
        organization=other_organization,
        customer=other_customer,
        user=user,
        number=4,
        total="999.00",
    )
    for order in (confirmed, draft, cancelled, hidden):
        _set_created(order, year=2026, month=8, day=15)

    report = order_report_for_organization(
        organization=organization,
        period="today",
        today=date(2026, 8, 15),
    )

    assert report["all"] == {"count": 3, "value": Decimal("60.00"), "ticket": Decimal("20.00")}
    assert report["confirmed"]["value"] == Decimal("30.00")
    assert report["drafts"]["count"] == 1
    assert report["cancelled"]["count"] == 1
    assert report["daily"] == [{"day": date(2026, 8, 15), "count": 3, "value": Decimal("60.00")}]


def test_empty_report_has_zero_ticket(organization, operator_membership):
    report = order_report_for_organization(
        organization=organization,
        period="today",
        today=date(2026, 8, 15),
    )
    assert report["all"] == {"count": 0, "value": Decimal("0.00"), "ticket": Decimal("0.00")}
    assert report["daily"] == []


def test_report_views_render_and_export_csv(
    client,
    organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Cliente CSV")
    order = _order(organization=organization, customer=customer, user=user, number=10, total="42.00")
    _set_created(order, year=timezone.localdate().year, month=timezone.localdate().month, day=timezone.localdate().day)
    client.force_login(user)

    page = client.get(reverse("dashboard:order-report"), {"period": "today"})
    export = client.get(reverse("dashboard:order-report-csv"), {"period": "today"})

    assert page.status_code == 200
    assert "Valor dos pedidos" in page.content.decode()
    assert export.status_code == 200
    assert export["Content-Type"].startswith("text/csv")
    csv_text = export.content.decode("utf-8-sig")
    assert "Quantidade de pedidos" in csv_text
    assert "42.00" in csv_text


def test_ready_pickups_are_filtered_searched_and_limited(
    organization,
    other_organization,
    user,
    operator_membership,
):
    customer = _customer(organization=organization, name="Maria Retirada")
    other_customer = _customer(organization=other_organization, name="Maria Oculta")
    order = _order(organization=organization, customer=customer, user=user, number=77)
    hidden_order = _order(organization=other_organization, customer=other_customer, user=user, number=88)
    unit = OrganizationUnit.objects.create(organization=organization, name="Balcão")
    hidden_unit = OrganizationUnit.objects.create(organization=other_organization, name="Outro")
    ready = Fulfillment.objects.create(
        organization=organization,
        order=order,
        sequence=1,
        method=Fulfillment.Method.PICKUP,
        status=Fulfillment.Status.READY,
        pickup_unit=unit,
        pickup_unit_name_snapshot=unit.name,
        ready_at=timezone.now(),
        created_by=user,
    )
    Fulfillment.objects.create(
        organization=organization,
        order=order,
        sequence=2,
        method=Fulfillment.Method.DELIVERY,
        status=Fulfillment.Status.READY,
        destination_snapshot={},
        ready_at=timezone.now(),
        created_by=user,
    )
    Fulfillment.objects.create(
        organization=other_organization,
        order=hidden_order,
        sequence=1,
        method=Fulfillment.Method.PICKUP,
        status=Fulfillment.Status.READY,
        pickup_unit=hidden_unit,
        pickup_unit_name_snapshot=hidden_unit.name,
        ready_at=timezone.now(),
        created_by=user,
    )

    assert list(ready_pickups_for_organization(organization=organization)) == [ready]
    assert list(ready_pickups_for_organization(organization=organization, query="Maria")) == [ready]
    assert list(ready_pickups_for_organization(organization=organization, query="PED-77")) == [ready]
    assert list(ready_pickups_for_organization(organization=organization, query="inexistente")) == []
    assert list(ready_pickups_for_organization(organization=organization, limit=0)) == []


def test_pickup_center_view_is_read_only(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    response = client.get(reverse("dashboard:pickups"), {"q": "Maria"})
    assert response.status_code == 200
    assert "Central de Retiradas" in response.content.decode()
    assert client.post(reverse("dashboard:pickups"), {}).status_code == 405
