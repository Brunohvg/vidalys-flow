from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.orders.models import Order

REPORT_PERIODS = {
    "today": "Hoje",
    "yesterday": "Ontem",
    "7d": "Últimos 7 dias",
    "month": "Este mês",
    "previous_month": "Mês anterior",
    "year": "Este ano",
}


def _aware_start(day):
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def report_range(*, period, today=None):
    today = today or timezone.localdate()
    if period == "today":
        start_day, end_day = today, today + timedelta(days=1)
    elif period == "yesterday":
        start_day, end_day = today - timedelta(days=1), today
    elif period == "7d":
        start_day, end_day = today - timedelta(days=6), today + timedelta(days=1)
    elif period == "previous_month":
        current_month = today.replace(day=1)
        previous_last = current_month - timedelta(days=1)
        start_day = previous_last.replace(day=1)
        end_day = current_month
    elif period == "year":
        start_day = today.replace(month=1, day=1)
        end_day = today.replace(year=today.year + 1, month=1, day=1)
    else:
        period = "month"
        start_day = today.replace(day=1)
        if start_day.month == 12:
            end_day = start_day.replace(year=start_day.year + 1, month=1)
        else:
            end_day = start_day.replace(month=start_day.month + 1)
    return period, _aware_start(start_day), _aware_start(end_day)


def _summary(queryset):
    aggregates = queryset.aggregate(count=Count("id"), value=Sum("total"))
    count = aggregates["count"] or 0
    value = aggregates["value"] or Decimal("0.00")
    ticket = value / count if count else Decimal("0.00")
    return {"count": count, "value": value, "ticket": ticket.quantize(Decimal("0.01"))}


def _period_queryset(*, organization, start, end):
    return Order.objects.filter(
        organization=organization,
        customer__organization=organization,
        created_at__gte=start,
        created_at__lt=end,
    )


def order_report_for_organization(*, organization, period="month", today=None):
    period, start, end = report_range(period=period, today=today)
    queryset = _period_queryset(organization=organization, start=start, end=end)
    confirmed = queryset.filter(status=Order.Status.CONFIRMED)
    cancelled = queryset.filter(status=Order.Status.CANCELLED)
    drafts = queryset.filter(status=Order.Status.DRAFT)
    daily = list(
        queryset.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"), value=Sum("total"))
        .order_by("day")
    )

    duration = end - start
    previous_end = start
    previous_start = previous_end - duration
    previous_queryset = _period_queryset(
        organization=organization,
        start=previous_start,
        end=previous_end,
    )

    return {
        "period": period,
        "period_label": REPORT_PERIODS[period],
        "start": start,
        "end": end,
        "all": _summary(queryset),
        "confirmed": _summary(confirmed),
        "cancelled": _summary(cancelled),
        "drafts": _summary(drafts),
        "daily": daily,
        "previous": {
            "start": previous_start,
            "end": previous_end,
            "all": _summary(previous_queryset),
            "confirmed": _summary(previous_queryset.filter(status=Order.Status.CONFIRMED)),
        },
    }
