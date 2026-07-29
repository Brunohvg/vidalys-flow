import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.customers import selectors, services
from apps.customers.exceptions import (
    CustomerPermissionDenied,
    DuplicateDocumentError,
    InvalidMergeError,
)
from apps.customers.models import ContactPoint, Customer, CustomerMerge, CustomerNote
from apps.organizations.models import Membership
from apps.platform.models import OutboxEvent


def create_customer(organization, actor, **overrides):
    values = {
        "customer_type": Customer.Type.INDIVIDUAL,
        "display_name": "Ana Cliente",
    }
    values.update(overrides)
    return services.create_customer(organization=organization, actor=actor, **values)


@pytest.mark.django_db
def test_create_customer_normalizes_contacts_and_records_audit_outbox(
    organization,
    user,
    operator_membership,
):
    customer = create_customer(
        organization,
        user,
        document="529.982.247-25",
        email=" ANA@EXAMPLE.COM ",
        phone="(11) 99999-1234",
    )
    assert customer.document_normalized == "52998224725"
    assert set(customer.contacts.values_list("normalized_value", flat=True)) == {
        "ana@example.com",
        "+5511999991234",
    }
    assert AuditEvent.objects.filter(organization=organization, action="customer.created").count() == 1
    assert OutboxEvent.objects.filter(organization=organization, event_type="customer.created").count() == 1


@pytest.mark.django_db
def test_service_rejects_user_without_membership(organization, outsider):
    with pytest.raises(CustomerPermissionDenied):
        create_customer(organization, outsider)


@pytest.mark.django_db
def test_document_is_unique_per_organization_not_globally(
    organization,
    other_organization,
    user,
    outsider,
    operator_membership,
):
    Membership.objects.create(
        organization=other_organization,
        user=outsider,
        role=Membership.Role.OPERATOR,
    )
    create_customer(organization, user, document="52998224725")
    with pytest.raises(DuplicateDocumentError):
        create_customer(organization, user, display_name="Duplicado", document="52998224725")
    second = create_customer(other_organization, outsider, document="52998224725")
    assert second.organization == other_organization


@pytest.mark.django_db
def test_database_constraint_rejects_duplicate_document(organization):
    Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="A",
        document_normalized="52998224725",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Customer.objects.create(
            organization=organization,
            customer_type=Customer.Type.INDIVIDUAL,
            display_name="B",
            document_normalized="52998224725",
        )


@pytest.mark.django_db
def test_selectors_are_scoped_and_hide_inactive(
    organization,
    other_organization,
    user,
    outsider,
    operator_membership,
):
    Membership.objects.create(
        organization=other_organization,
        user=outsider,
        role=Membership.Role.OPERATOR,
    )
    visible = create_customer(organization, user, display_name="Visível")
    create_customer(other_organization, outsider, display_name="Oculto")
    services.set_customer_status(
        organization=organization,
        customer=visible,
        actor=user,
        status=Customer.Status.INACTIVE,
    )
    assert list(selectors.search_customers(organization=organization)) == []
    assert list(selectors.search_customers(organization=organization, include_inactive=True)) == [visible]


@pytest.mark.django_db
def test_inactive_membership_blocks_service(organization, user, operator_membership):
    operator_membership.is_active = False
    operator_membership.save(update_fields=("is_active",))
    with pytest.raises(CustomerPermissionDenied):
        create_customer(organization, user)


@pytest.mark.django_db
def test_primary_contact_is_replaced_and_shared_email_is_advisory(
    organization,
    user,
    operator_membership,
):
    first = create_customer(organization, user, display_name="Primeiro")
    second = create_customer(organization, user, display_name="Segundo")
    services.add_contact(
        organization=organization,
        customer=first,
        actor=user,
        kind=ContactPoint.Kind.EMAIL,
        value="shared@example.com",
        is_primary=True,
    )
    services.add_contact(
        organization=organization,
        customer=first,
        actor=user,
        kind=ContactPoint.Kind.EMAIL,
        value="new@example.com",
        is_primary=True,
    )
    services.add_contact(
        organization=organization,
        customer=second,
        actor=user,
        kind=ContactPoint.Kind.EMAIL,
        value="shared@example.com",
        is_primary=True,
    )
    assert first.contacts.get(normalized_value="new@example.com").is_primary
    assert not first.contacts.get(normalized_value="shared@example.com").is_primary
    assert set(
        selectors.duplicate_candidates(
            organization=organization,
            email="shared@example.com",
        ).values_list("id", flat=True)
    ) == {first.id, second.id}


@pytest.mark.django_db
def test_default_address_is_replaced(organization, user, operator_membership):
    customer = create_customer(organization, user)
    first = services.add_address(
        organization=organization,
        customer=customer,
        actor=user,
        street="Rua A",
        city="São Paulo",
        state="SP",
        is_default_shipping=True,
    )
    second = services.add_address(
        organization=organization,
        customer=customer,
        actor=user,
        street="Rua B",
        city="São Paulo",
        state="SP",
        is_default_shipping=True,
    )
    first.refresh_from_db()
    assert not first.is_default_shipping
    assert second.is_default_shipping


@pytest.mark.django_db
def test_note_is_sanitized_from_audit_and_logically_removed(organization, user, operator_membership):
    customer = create_customer(organization, user)
    secret_text = "Informação pessoal que não deve ir ao evento"
    note = services.add_note(
        organization=organization,
        customer=customer,
        actor=user,
        content=secret_text,
    )
    event = AuditEvent.objects.get(action="customer.note_added")
    assert secret_text not in str(event.payload)
    services.remove_note(organization=organization, note=note, actor=user)
    note.refresh_from_db()
    assert not note.is_active
    assert CustomerNote.objects.filter(customer=customer).count() == 1


@pytest.mark.django_db
def test_merge_moves_relations_and_is_audited(
    organization,
    manager,
    manager_membership,
):
    source = create_customer(organization, manager, display_name="Origem")
    target = create_customer(organization, manager, display_name="Destino")
    services.add_contact(
        organization=organization,
        customer=source,
        actor=manager,
        kind=ContactPoint.Kind.PHONE,
        value="11999991234",
        is_primary=True,
    )
    services.add_note(
        organization=organization,
        customer=source,
        actor=manager,
        content="Nota operacional",
    )
    merge = services.merge_customers(
        organization=organization,
        source=source,
        target=target,
        actor=manager,
        reason="Cadastro duplicado confirmado",
    )
    source.refresh_from_db()
    assert source.merged_into == target
    assert source.status == Customer.Status.INACTIVE
    assert target.contacts.count() == 1
    assert target.notes.count() == 1
    assert AuditEvent.objects.filter(action="customer.merged", entity_id=str(target.id)).exists()
    assert OutboxEvent.objects.filter(event_type="customer.merged").count() == 1
    with pytest.raises(TypeError):
        merge.delete()


@pytest.mark.django_db
def test_merge_rejects_cross_organization(
    organization,
    other_organization,
    manager,
    manager_membership,
):
    source = create_customer(organization, manager, display_name="Origem")
    target = Customer.objects.create(
        organization=other_organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Outro tenant",
    )
    with pytest.raises(InvalidMergeError):
        services.merge_customers(
            organization=organization,
            source=source,
            target=target,
            actor=manager,
            reason="Inválido",
        )
    assert CustomerMerge.objects.count() == 0
