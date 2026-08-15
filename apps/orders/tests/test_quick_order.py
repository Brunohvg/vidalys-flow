import uuid
from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.customers.models import Customer
from apps.fulfillment.models import Fulfillment
from apps.orders.models import Order
from apps.orders.quick_forms import QuickOrderCreateForm
from apps.orders.quick_services import create_quick_order


@pytest.mark.django_db
def test_quick_manual_order_creates_customer_and_preserves_manual_total(
    organization,
    user,
    operator_membership,
):
    order = create_quick_order(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer_name="Ana Ferreira",
        customer_phone="31999999999",
        pricing_mode=Order.PricingMode.MANUAL,
        manual_total=Decimal("180.00"),
    )

    assert order.customer.display_name == "Ana Ferreira"
    assert order.pricing_mode == Order.PricingMode.MANUAL
    assert order.manual_total == Decimal("180.00")
    assert order.subtotal == Decimal("180.00")
    assert order.total == Decimal("180.00")
    assert order.items.count() == 0
    audit = AuditEvent.objects.get(organization=organization, entity_type="order", entity_id=str(order.id))
    assert audit.payload["inline_customer_created"] is True


@pytest.mark.django_db
def test_quick_order_retry_does_not_duplicate_inline_customer(
    organization,
    user,
    operator_membership,
):
    key = str(uuid.uuid4())
    kwargs = {
        "organization": organization,
        "actor": user,
        "idempotency_key": key,
        "customer_name": "Cliente idempotente",
        "customer_phone": "31988887777",
        "pricing_mode": Order.PricingMode.MANUAL,
        "manual_total": Decimal("99.90"),
    }

    first = create_quick_order(**kwargs)
    second = create_quick_order(**kwargs)

    assert second.id == first.id
    assert Customer.objects.filter(organization=organization, display_name="Cliente idempotente").count() == 1
    assert Order.objects.filter(organization=organization).count() == 1


@pytest.mark.django_db
def test_quick_order_reuses_exact_document_without_name_merge(
    organization,
    user,
    operator_membership,
    customer,
):
    before = Customer.objects.filter(organization=organization).count()

    order = create_quick_order(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer_name="Nome diferente informado no balcão",
        customer_document="529.982.247-25",
        pricing_mode=Order.PricingMode.MANUAL,
        manual_total=Decimal("50.00"),
    )

    assert order.customer_id == customer.id
    assert Customer.objects.filter(organization=organization).count() == before
    audit = AuditEvent.objects.get(organization=organization, entity_type="order", entity_id=str(order.id))
    assert audit.payload["inline_customer_created"] is False


@pytest.mark.django_db
def test_itemized_quick_order_starts_without_manual_source(
    organization,
    user,
    operator_membership,
    customer,
):
    order = create_quick_order(
        organization=organization,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
        customer=customer,
        pricing_mode=Order.PricingMode.ITEMIZED,
    )

    assert order.pricing_mode == Order.PricingMode.ITEMIZED
    assert order.manual_total is None
    assert order.total == Decimal("0.00")


@pytest.mark.django_db
def test_quick_order_can_add_default_shipping_address_atomically(
    organization,
    user,
    operator_membership,
):
    key = str(uuid.uuid4())
    kwargs = {
        "organization": organization,
        "actor": user,
        "idempotency_key": key,
        "customer_name": "Cliente entrega",
        "pricing_mode": Order.PricingMode.MANUAL,
        "manual_total": Decimal("125.00"),
        "has_delivery_address": True,
        "delivery_postal_code": "30130110",
        "delivery_street": "Rua da Bahia",
        "delivery_number": "100",
        "delivery_complement": "Sala 2",
        "delivery_district": "Centro",
        "delivery_city": "Belo Horizonte",
        "delivery_state": "MG",
    }

    first = create_quick_order(**kwargs)
    repeated = create_quick_order(**kwargs)
    address = first.customer.addresses.get()

    assert repeated.id == first.id
    assert first.customer.addresses.count() == 1
    assert address.is_default_shipping is True
    assert address.postal_code == "30130110"
    assert address.city == "Belo Horizonte"
    assert address.state == "MG"


@pytest.mark.django_db
def test_quick_order_form_rejects_partial_delivery_address(organization):
    form = QuickOrderCreateForm(
        data={
            "customer_name": "Cliente entrega incompleta",
            "pricing_mode": Order.PricingMode.MANUAL,
            "manual_total": "50.00",
            "fulfillment_method": Fulfillment.Method.DELIVERY,
            "delivery_postal_code": "30130-110",
            "delivery_street": "Rua da Bahia",
            "idempotency_key": str(uuid.uuid4()),
        },
        organization=organization,
    )

    assert not form.is_valid()
    assert "delivery_city" in form.errors
    assert "delivery_state" in form.errors


@pytest.mark.django_db
def test_quick_order_form_normalizes_manual_delivery_cep_and_state(organization):
    form = QuickOrderCreateForm(
        data={
            "customer_name": "Cliente entrega completa",
            "pricing_mode": Order.PricingMode.MANUAL,
            "manual_total": "50.00",
            "fulfillment_method": Fulfillment.Method.DELIVERY,
            "delivery_postal_code": "30130-110",
            "delivery_street": "Rua da Bahia",
            "delivery_city": "Belo Horizonte",
            "delivery_state": "mg",
            "idempotency_key": str(uuid.uuid4()),
        },
        organization=organization,
    )

    assert form.is_valid()
    assert form.cleaned_data["has_delivery_address"] is True
    assert form.cleaned_data["delivery_postal_code"] == "30130110"
    assert form.cleaned_data["delivery_state"] == "MG"
