from django.db import IntegrityError, transaction

from apps.audit.services import record_event
from apps.customers import policies, selectors
from apps.customers.events import (
    CUSTOMER_CREATED,
    CUSTOMER_MERGED,
    CUSTOMER_NOTE_ADDED,
    CUSTOMER_NOTE_REMOVED,
    CUSTOMER_STATUS_CHANGED,
    CUSTOMER_UPDATED,
)
from apps.customers.exceptions import (
    BlockReasonRequiredError,
    CustomerMergedError,
    CustomerOrganizationMismatch,
    CustomerPermissionDenied,
    DuplicateDocumentError,
    InvalidDocumentError,
    InvalidMergeError,
)
from apps.customers.models import ContactPoint, Customer, CustomerAddress, CustomerMerge, CustomerNote
from apps.customers.normalization import normalize_document, normalize_email, normalize_phone
from apps.platform.services import enqueue_event


def _require_permission(*, actor, organization, manager=False):
    allowed = (
        policies.can_merge_customers(user=actor, organization=organization)
        if manager
        else policies.can_manage_customers(user=actor, organization=organization)
    )
    if not allowed:
        raise CustomerPermissionDenied("Membership ativa insuficiente.")


def _require_customer(*, organization, customer):
    if customer.organization_id != organization.id:
        raise CustomerOrganizationMismatch("Cliente não pertence à organização.")
    if customer.is_merged:
        raise CustomerMergedError("O cliente foi mesclado; use o registro canônico.")


def _normalized_document(*, customer_type, document):
    try:
        normalized = normalize_document(document)
    except ValueError as exc:
        raise InvalidDocumentError(str(exc)) from exc
    if normalized and customer_type == Customer.Type.INDIVIDUAL and len(normalized) != 11:
        raise InvalidDocumentError("Pessoa física deve usar CPF.")
    if normalized and customer_type == Customer.Type.COMPANY and len(normalized) != 14:
        raise InvalidDocumentError("Pessoa jurídica deve usar CNPJ.")
    return normalized


@transaction.atomic
def create_customer(
    *,
    organization,
    actor,
    customer_type,
    display_name,
    legal_name="",
    document="",
    notes_summary="",
    email="",
    phone="",
):
    _require_permission(actor=actor, organization=organization)
    document_normalized = _normalized_document(customer_type=customer_type, document=document)
    try:
        with transaction.atomic():
            customer = Customer.objects.create(
                organization=organization,
                customer_type=customer_type,
                display_name=display_name.strip(),
                legal_name=legal_name.strip(),
                document_normalized=document_normalized,
                notes_summary=notes_summary.strip(),
            )
    except IntegrityError as exc:
        if document_normalized and selectors.find_by_document(
            organization=organization,
            document_normalized=document_normalized,
        ):
            raise DuplicateDocumentError("Documento já cadastrado nesta organização.") from exc
        raise

    if email:
        _add_contact(customer=customer, kind=ContactPoint.Kind.EMAIL, value=email, is_primary=True)
    if phone:
        _add_contact(customer=customer, kind=ContactPoint.Kind.PHONE, value=phone, is_primary=True)

    record_event(
        organization=organization,
        actor=actor,
        action=CUSTOMER_CREATED,
        entity_type="customer",
        entity_id=customer.id,
        payload={"customer_type": customer.customer_type},
    )
    enqueue_event(
        organization=organization,
        event_type=CUSTOMER_CREATED,
        aggregate_type="customer",
        aggregate_id=customer.id,
        payload={"customer_id": str(customer.id)},
        idempotency_key=f"customer-created-{customer.id}",
    )
    return customer


@transaction.atomic
def update_customer(
    *,
    organization,
    customer,
    actor,
    display_name,
    legal_name="",
    notes_summary="",
):
    _require_permission(actor=actor, organization=organization)
    _require_customer(organization=organization, customer=customer)
    changed_fields = []
    for field, value in {
        "display_name": display_name.strip(),
        "legal_name": legal_name.strip(),
        "notes_summary": notes_summary.strip(),
    }.items():
        if getattr(customer, field) != value:
            setattr(customer, field, value)
            changed_fields.append(field)
    if changed_fields:
        customer.save(update_fields=(*changed_fields, "updated_at"))
        record_event(
            organization=organization,
            actor=actor,
            action=CUSTOMER_UPDATED,
            entity_type="customer",
            entity_id=customer.id,
            payload={"changed_fields": changed_fields},
        )
    return customer


@transaction.atomic
def set_customer_status(*, organization, customer, actor, status, reason=""):
    _require_permission(
        actor=actor,
        organization=organization,
        manager=status == Customer.Status.BLOCKED,
    )
    _require_customer(organization=organization, customer=customer)
    if status == Customer.Status.BLOCKED and not reason.strip():
        raise BlockReasonRequiredError("Bloqueio exige motivo.")
    if customer.status == status:
        return customer
    before = customer.status
    customer.status = status
    customer.save(update_fields=("status", "updated_at"))
    record_event(
        organization=organization,
        actor=actor,
        action=CUSTOMER_STATUS_CHANGED,
        entity_type="customer",
        entity_id=customer.id,
        payload={"before": before, "after": status, "reason_provided": bool(reason.strip())},
    )
    return customer


def _normalize_contact(kind, value):
    return normalize_email(value) if kind == ContactPoint.Kind.EMAIL else normalize_phone(value)


def _add_contact(*, customer, kind, value, is_primary=False):
    normalized = _normalize_contact(kind, value)
    existing = customer.contacts.filter(
        kind=kind,
        normalized_value=normalized,
        is_active=True,
    ).first()
    if existing:
        return existing
    if is_primary:
        Customer.objects.select_for_update().get(id=customer.id)
        customer.contacts.filter(kind=kind, is_primary=True, is_active=True).update(is_primary=False)
    return ContactPoint.objects.create(
        customer=customer,
        kind=kind,
        value=value.strip(),
        normalized_value=normalized,
        is_primary=is_primary,
    )


@transaction.atomic
def add_contact(*, organization, customer, actor, kind, value, is_primary=False):
    _require_permission(actor=actor, organization=organization)
    _require_customer(organization=organization, customer=customer)
    contact = _add_contact(customer=customer, kind=kind, value=value, is_primary=is_primary)
    record_event(
        organization=organization,
        actor=actor,
        action="customer.contact_added",
        entity_type="customer",
        entity_id=customer.id,
        payload={"contact_id": str(contact.id), "kind": contact.kind},
    )
    return contact


@transaction.atomic
def add_address(
    *,
    organization,
    customer,
    actor,
    label="",
    recipient_name="",
    postal_code="",
    street,
    number="",
    complement="",
    district="",
    city,
    state,
    country="BR",
    reference="",
    is_default_shipping=False,
    is_default_billing=False,
):
    _require_permission(actor=actor, organization=organization)
    _require_customer(organization=organization, customer=customer)
    if is_default_shipping or is_default_billing:
        Customer.objects.select_for_update().get(id=customer.id)
    if is_default_shipping:
        customer.addresses.filter(is_default_shipping=True, is_active=True).update(is_default_shipping=False)
    if is_default_billing:
        customer.addresses.filter(is_default_billing=True, is_active=True).update(is_default_billing=False)
    address = CustomerAddress.objects.create(
        customer=customer,
        label=label.strip(),
        recipient_name=recipient_name.strip(),
        postal_code=postal_code.strip(),
        street=street.strip(),
        number=number.strip(),
        complement=complement.strip(),
        district=district.strip(),
        city=city.strip(),
        state=state.strip().upper(),
        country=country.strip().upper(),
        reference=reference.strip(),
        is_default_shipping=is_default_shipping,
        is_default_billing=is_default_billing,
    )
    record_event(
        organization=organization,
        actor=actor,
        action="customer.address_added",
        entity_type="customer",
        entity_id=customer.id,
        payload={"address_id": str(address.id)},
    )
    return address


@transaction.atomic
def add_note(*, organization, customer, actor, content):
    _require_permission(actor=actor, organization=organization)
    _require_customer(organization=organization, customer=customer)
    note = CustomerNote.objects.create(
        organization=organization,
        customer=customer,
        author=actor,
        content=content.strip(),
    )
    record_event(
        organization=organization,
        actor=actor,
        action=CUSTOMER_NOTE_ADDED,
        entity_type="customer",
        entity_id=customer.id,
        payload={"note_id": str(note.id)},
    )
    return note


@transaction.atomic
def remove_note(*, organization, note, actor):
    _require_permission(actor=actor, organization=organization)
    if note.organization_id != organization.id:
        raise CustomerOrganizationMismatch("Nota não pertence à organização.")
    if not note.is_active:
        return note
    note.is_active = False
    note.save(update_fields=("is_active", "updated_at"))
    record_event(
        organization=organization,
        actor=actor,
        action=CUSTOMER_NOTE_REMOVED,
        entity_type="customer",
        entity_id=note.customer_id,
        payload={"note_id": str(note.id)},
    )
    return note


@transaction.atomic
def merge_customers(*, organization, source, target, actor, reason):
    _require_permission(actor=actor, organization=organization, manager=True)
    if source.id == target.id:
        raise InvalidMergeError("Origem e destino devem ser diferentes.")
    locked = {
        customer.id: customer
        for customer in Customer.objects.select_for_update()
        .filter(id__in=(source.id, target.id))
        .order_by("id")
    }
    source = locked.get(source.id)
    target = locked.get(target.id)
    invalid_scope = (
        not source
        or not target
        or source.organization_id != organization.id
        or target.organization_id != organization.id
    )
    if invalid_scope:
        raise InvalidMergeError("Origem e destino devem pertencer à organização.")
    if source.is_merged or target.is_merged:
        raise InvalidMergeError("Cliente já mesclado não pode participar de nova mesclagem.")

    rules = {"contacts_moved": 0, "contacts_deactivated": 0, "addresses_moved": 0, "notes_moved": 0}
    for contact in source.contacts.filter(is_active=True):
        duplicate = target.contacts.filter(
            kind=contact.kind,
            normalized_value=contact.normalized_value,
            is_active=True,
        ).first()
        if duplicate:
            contact.is_active = False
            contact.is_primary = False
            contact.save(update_fields=("is_active", "is_primary", "updated_at"))
            rules["contacts_deactivated"] += 1
            continue
        if contact.is_primary and target.contacts.filter(kind=contact.kind, is_primary=True, is_active=True).exists():
            contact.is_primary = False
        contact.customer = target
        contact.save(update_fields=("customer", "is_primary", "updated_at"))
        rules["contacts_moved"] += 1

    for address in source.addresses.filter(is_active=True):
        if address.is_default_shipping and target.addresses.filter(
            is_default_shipping=True,
            is_active=True,
        ).exists():
            address.is_default_shipping = False
        if address.is_default_billing and target.addresses.filter(
            is_default_billing=True,
            is_active=True,
        ).exists():
            address.is_default_billing = False
        address.customer = target
        address.save(
            update_fields=("customer", "is_default_shipping", "is_default_billing", "updated_at")
        )
        rules["addresses_moved"] += 1

    rules["notes_moved"] = source.notes.update(customer=target)
    source.status = Customer.Status.INACTIVE
    source.merged_into = target
    source.save(update_fields=("status", "merged_into", "updated_at"))
    merge = CustomerMerge.objects.create(
        organization=organization,
        source_customer=source,
        target_customer=target,
        performed_by=actor,
        reason=reason.strip(),
        rules_applied=rules,
    )
    record_event(
        organization=organization,
        actor=actor,
        action=CUSTOMER_MERGED,
        entity_type="customer",
        entity_id=target.id,
        payload={"source_id": str(source.id), "rules_applied": rules},
    )
    enqueue_event(
        organization=organization,
        event_type=CUSTOMER_MERGED,
        aggregate_type="customer",
        aggregate_id=target.id,
        payload={"source_id": str(source.id), "target_id": str(target.id)},
        idempotency_key=f"customer-merged-{merge.id}",
    )
    return merge
