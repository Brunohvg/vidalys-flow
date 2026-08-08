from django.db.models import Q, Sum

from apps.fulfillment.models import Fulfillment, FulfillmentItem
from apps.fulfillment.policies import MANAGER_ROLES


def fulfillments_for_organization(*, organization):
    return Fulfillment.objects.filter(organization=organization).select_related(
        "order",
        "order__customer",
        "pickup_unit",
        "created_by",
    )


def search_fulfillments(*, organization, query="", status="", method=""):
    queryset = fulfillments_for_organization(organization=organization)
    query = (query or "").strip()
    if query:
        numeric = query.upper().removeprefix("PED-").split("-F", 1)[0]
        filters = Q(order__customer_name_snapshot__icontains=query)
        if numeric.isdigit():
            filters |= Q(order__number=int(numeric))
        queryset = queryset.filter(filters)
    if status:
        queryset = queryset.filter(status=status)
    if method:
        queryset = queryset.filter(method=method)
    return queryset


def fulfillment_for_organization(*, organization, fulfillment_id):
    return fulfillments_for_organization(organization=organization).filter(id=fulfillment_id).first()


def order_allocations(*, organization, order):
    rows = (
        FulfillmentItem.objects.filter(
            organization=organization,
            order_item__order=order,
        )
        .exclude(fulfillment__status=Fulfillment.Status.CANCELLED)
        .values("order_item_id")
        .annotate(total=Sum("quantity"))
    )
    return {row["order_item_id"]: row["total"] for row in rows}


def fulfillment_detail(*, organization, fulfillment, user, membership):
    if fulfillment.organization_id != organization.id:
        return None
    if (
        membership.organization_id != organization.id
        or membership.user_id != user.id
        or not membership.is_active
    ):
        return None
    unmasked = membership.role in MANAGER_ROLES
    destination = fulfillment.destination_snapshot
    return {
        "display_number": fulfillment.display_number,
        "destination": destination if unmasked else _masked_address(destination),
        "items": fulfillment.items.select_related("order_item").order_by("order_item__position"),
        "history": fulfillment.status_history.select_related("actor").all(),
    }


def _masked_address(address):
    if not address:
        return {}
    postal_code = address["postal_code"]
    return {
        "schema_version": address["schema_version"],
        "recipient_name": "••••" if address["recipient_name"] else "",
        "postal_code": f"•••••-{postal_code[-3:]}" if postal_code else "",
        "street": "••••",
        "number": "••",
        "complement": "••••" if address["complement"] else "",
        "district": "••••" if address["district"] else "",
        "city": address["city"],
        "state": address["state"],
        "country": address["country"],
    }
