from apps.customers.models import ContactPoint

SNAPSHOT_SCHEMA_VERSION = 1
CONTACT_PRIORITY = {
    ContactPoint.Kind.WHATSAPP: 0,
    ContactPoint.Kind.PHONE: 1,
    ContactPoint.Kind.EMAIL: 2,
}


def customer_snapshots(customer):
    contacts = list(customer.contacts.filter(is_active=True))
    contacts.sort(key=lambda item: (not item.is_primary, CONTACT_PRIORITY[item.kind], item.created_at))
    contact = contacts[0] if contacts else None
    shipping = customer.addresses.filter(is_active=True, is_default_shipping=True).first()
    billing = customer.addresses.filter(is_active=True, is_default_billing=True).first()
    return {
        "customer_name_snapshot": customer.display_name,
        "customer_document_snapshot": customer.document_normalized,
        "customer_contact_snapshot": _contact_snapshot(contact),
        "shipping_address_snapshot": _address_snapshot(shipping),
        "billing_address_snapshot": _address_snapshot(billing),
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
    }


def _contact_snapshot(contact):
    if contact is None:
        return {}
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "kind": contact.kind,
        "value": contact.normalized_value,
    }


def _address_snapshot(address):
    if address is None:
        return {}
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "recipient_name": address.recipient_name,
        "postal_code": address.postal_code,
        "street": address.street,
        "number": address.number,
        "complement": address.complement,
        "district": address.district,
        "city": address.city,
        "state": address.state,
        "country": address.country,
    }
