from django.db.models import Q

from apps.customers.normalization import mask_contact, mask_document
from apps.orders.models import Order
from apps.orders.policies import MANAGER_ROLES
from apps.orders.snapshots import customer_snapshots


def orders_for_organization(*, organization):
    return Order.objects.filter(organization=organization).select_related("customer", "created_by")


def search_orders(
    *,
    organization,
    query="",
    status="",
    channel="",
    created_from=None,
    created_to=None,
):
    queryset = orders_for_organization(organization=organization)
    query = (query or "").strip()
    if query:
        numeric = query.upper().removeprefix("PED-")
        filters = Q(customer__display_name__icontains=query) | Q(customer_name_snapshot__icontains=query)
        if numeric.isdigit():
            filters |= Q(number=int(numeric))
        queryset = queryset.filter(filters)
    if status:
        queryset = queryset.filter(status=status)
    if channel:
        queryset = queryset.filter(channel__iexact=channel.strip())
    if created_from:
        queryset = queryset.filter(created_at__date__gte=created_from)
    if created_to:
        queryset = queryset.filter(created_at__date__lte=created_to)
    return queryset


def order_for_organization(*, organization, order_id, for_update=False):
    queryset = Order.objects.filter(organization=organization, id=order_id)
    if for_update:
        queryset = queryset.select_for_update()
    return queryset.first()


def order_detail(*, organization, order, membership):
    if order.organization_id != organization.id:
        return None
    unmasked = membership.role in MANAGER_ROLES
    snapshots = {
        "customer_document_snapshot": order.customer_document_snapshot,
        "customer_contact_snapshot": order.customer_contact_snapshot,
        "shipping_address_snapshot": order.shipping_address_snapshot,
        "billing_address_snapshot": order.billing_address_snapshot,
    }
    if order.status == Order.Status.DRAFT:
        current = customer_snapshots(order.customer)
        snapshots = {field: value or current[field] for field, value in snapshots.items()}
    document = snapshots["customer_document_snapshot"]
    contact = snapshots["customer_contact_snapshot"]
    shipping = snapshots["shipping_address_snapshot"]
    billing = snapshots["billing_address_snapshot"]
    return {
        "display_number": order.display_number,
        "customer_name": order.customer_name_snapshot or order.customer.display_name,
        "customer_document": document if unmasked else mask_document(document),
        "customer_contact": _contact_for_display(contact, unmasked=unmasked),
        "shipping_address": shipping if unmasked else _masked_address(shipping),
        "billing_address": billing if unmasked else _masked_address(billing),
        "items": order.items.select_related("product", "variant").all(),
        "history": order.status_history.select_related("actor").all(),
    }


def _contact_for_display(contact, *, unmasked):
    if not contact:
        return {}
    return {
        "kind": contact["kind"],
        "value": (
            contact["value"]
            if unmasked
            else mask_contact(contact["kind"], contact["value"])
        ),
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
