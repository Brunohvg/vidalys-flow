from django.db.models import Q

from apps.customers.models import ContactPoint, Customer
from apps.customers.normalization import mask_contact, mask_document
from apps.customers.policies import MANAGER_ROLES


def customers_for_organization(*, organization, include_inactive=False):
    queryset = Customer.objects.filter(organization=organization, merged_into__isnull=True)
    if not include_inactive:
        queryset = queryset.filter(status=Customer.Status.ACTIVE)
    return queryset


def search_customers(*, organization, query="", include_inactive=False):
    queryset = customers_for_organization(organization=organization, include_inactive=include_inactive)
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(
        Q(display_name__icontains=query)
        | Q(legal_name__icontains=query)
        | Q(document_normalized=query)
        | Q(contacts__normalized_value__icontains=query)
    ).distinct()


def customer_for_organization(*, organization, customer_id, include_merged=False):
    queryset = Customer.objects.filter(organization=organization, id=customer_id)
    if not include_merged:
        queryset = queryset.filter(merged_into__isnull=True)
    return queryset.first()


def resolve_canonical(*, organization, customer_id):
    current = customer_for_organization(
        organization=organization,
        customer_id=customer_id,
        include_merged=True,
    )
    seen = set()
    while current and current.merged_into_id and current.id not in seen:
        seen.add(current.id)
        current = customer_for_organization(
            organization=organization,
            customer_id=current.merged_into_id,
            include_merged=True,
        )
    return current


def find_by_document(*, organization, document_normalized):
    if not document_normalized:
        return None
    return Customer.objects.filter(
        organization=organization,
        document_normalized=document_normalized,
        merged_into__isnull=True,
    ).first()


def duplicate_candidates(*, organization, email="", phone="", exclude_customer_id=None):
    filters = Q()
    if email:
        filters |= Q(contacts__kind=ContactPoint.Kind.EMAIL, contacts__normalized_value=email)
    if phone:
        filters |= Q(
            contacts__kind__in=(ContactPoint.Kind.PHONE, ContactPoint.Kind.WHATSAPP),
            contacts__normalized_value=phone,
        )
    if not filters:
        return Customer.objects.none()
    queryset = Customer.objects.filter(
        organization=organization,
        merged_into__isnull=True,
        contacts__is_active=True,
    ).filter(filters)
    if exclude_customer_id:
        queryset = queryset.exclude(id=exclude_customer_id)
    return queryset.distinct()


def customer_detail(*, organization, customer, membership):
    if customer.organization_id != organization.id:
        return None
    full_access = membership.role in MANAGER_ROLES
    return {
        "document": (
            customer.document_normalized
            if full_access
            else mask_document(customer.document_normalized)
        ),
        "contacts": [
            {
                "kind": contact.get_kind_display(),
                "value": (
                    contact.value
                    if full_access
                    else mask_contact(contact.kind, contact.normalized_value)
                ),
                "is_primary": contact.is_primary,
            }
            for contact in customer.contacts.filter(is_active=True)
        ],
        "addresses": customer.addresses.filter(is_active=True),
        "notes": customer.notes.filter(is_active=True),
    }
