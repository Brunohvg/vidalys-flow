import uuid

import pytest

from apps.customers.models import ContactPoint
from apps.customers.services import add_contact
from apps.orders.selectors import order_detail, search_orders
from apps.orders.services import add_item, confirm_order
from apps.organizations.models import Membership


@pytest.mark.django_db
def test_search_is_scoped_and_accepts_display_number(organization, other_organization, order):
    assert list(search_orders(organization=organization, query=order.display_number)) == [order]
    assert not search_orders(organization=other_organization, query=order.display_number).exists()
    assert list(search_orders(organization=organization, status="draft", channel="WHATSAPP")) == [order]


@pytest.mark.django_db
def test_operator_detail_masks_confirmed_personal_data(
    organization,
    order,
    customer,
    user,
    operator_membership,
):
    add_contact(
        organization=organization,
        customer=customer,
        actor=user,
        kind=ContactPoint.Kind.EMAIL,
        value="person@example.com",
        is_primary=True,
    )
    add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
        name="Item",
        quantity=1,
        unit_price=10,
    )
    confirm_order(
        organization=organization,
        order=order,
        actor=user,
        expected_version=2,
        idempotency_key=str(uuid.uuid4()),
    )
    order.refresh_from_db()
    detail = order_detail(
        organization=organization,
        order=order,
        membership=operator_membership,
    )
    assert detail["customer_document"].endswith("4725")
    assert detail["customer_document"] != "52998224725"
    assert detail["customer_contact"]["value"] == "pe***@example.com"


@pytest.mark.django_db
def test_operator_detail_masks_address(organization, order, user, operator_membership):
    order.shipping_address_snapshot = {
        "schema_version": 1,
        "recipient_name": "Pessoa",
        "postal_code": "01001000",
        "street": "Praça da Sé",
        "number": "10",
        "complement": "Apto 1",
        "district": "Sé",
        "city": "São Paulo",
        "state": "SP",
        "country": "BR",
    }
    order.save(update_fields=("shipping_address_snapshot", "updated_at"))
    detail = order_detail(
        organization=organization,
        order=order,
        membership=operator_membership,
    )
    assert detail["shipping_address"]["street"] == "••••"
    assert detail["shipping_address"]["postal_code"].endswith("000")
    assert "Praça da Sé" not in str(detail)


@pytest.mark.django_db
def test_manager_detail_is_unmasked(organization, order, manager, manager_membership):
    assert manager_membership.role == Membership.Role.MANAGER
    order.customer_document_snapshot = "52998224725"
    order.customer_contact_snapshot = {"schema_version": 1, "kind": "email", "value": "person@example.com"}
    order.save(update_fields=("customer_document_snapshot", "customer_contact_snapshot", "updated_at"))
    detail = order_detail(
        organization=organization,
        order=order,
        membership=manager_membership,
    )
    assert detail["customer_document"] == "52998224725"
    assert detail["customer_contact"]["value"] == "person@example.com"


@pytest.mark.django_db
def test_draft_detail_uses_current_customer_data_with_role_masking(
    organization,
    order,
    customer,
    user,
    operator_membership,
    manager_membership,
):
    add_contact(
        organization=organization,
        customer=customer,
        actor=user,
        kind=ContactPoint.Kind.EMAIL,
        value="draft@example.com",
        is_primary=True,
    )
    operator_detail = order_detail(
        organization=organization,
        order=order,
        membership=operator_membership,
    )
    manager_detail = order_detail(
        organization=organization,
        order=order,
        membership=manager_membership,
    )
    assert operator_detail["customer_document"] != "52998224725"
    assert operator_detail["customer_contact"]["value"] == "dr***@example.com"
    assert manager_detail["customer_document"] == "52998224725"
    assert manager_detail["customer_contact"]["value"] == "draft@example.com"
