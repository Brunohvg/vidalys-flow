from django.db.models import Q

from apps.fulfillment.models import Fulfillment

PICKUP_CENTER_LIMIT = 100


def ready_pickups_for_organization(*, organization, query="", limit=PICKUP_CENTER_LIMIT):
    queryset = (
        Fulfillment.objects.filter(
            organization=organization,
            order__organization=organization,
            order__customer__organization=organization,
            method=Fulfillment.Method.PICKUP,
            status=Fulfillment.Status.READY,
        )
        .select_related("order", "order__customer", "pickup_unit")
        .order_by("ready_at", "created_at")
    )
    query = (query or "").strip()
    if query:
        numeric = query.upper().removeprefix("PED-").split("-F", 1)[0]
        filters = Q(order__customer_name_snapshot__icontains=query) | Q(order__customer__display_name__icontains=query)
        if numeric.isdigit():
            filters |= Q(order__number=int(numeric))
        queryset = queryset.filter(filters)
    return queryset[:limit]
