import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.dashboard.order_actions import order_next_action
from apps.fulfillment.models import Fulfillment
from apps.orders.models import Order
from apps.organizations.models import OrganizationUnit
from apps.payments.manual_services import confirm_manual_payment
from apps.payments.models import PaymentIntent, PixPaymentInstruction
from apps.payments.pix_services import configure_pix_instruction
from apps.payments.services import create_payment_intent

pytestmark = pytest.mark.django_db


@pytest.fixture
def payable_order(organization, manager, manager_membership):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente Dashboard",
    )
    return Order.objects.create(
        organization=organization,
        number=501,
        customer=customer,
        status=Order.Status.CONFIRMED,
        currency="BRL",
        subtotal=Decimal("125.40"),
        total=Decimal("125.40"),
        customer_name_snapshot=customer.display_name,
        created_by=manager,
        confirmed_at=timezone.now(),
    )


def _paid_intent(*, organization, order, manager):
    payment = create_payment_intent(
        organization=organization,
        order=order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    return confirm_manual_payment(
        organization=organization,
        intent=payment,
        actor=manager,
        expected_version=payment.version,
        idempotency_key=str(uuid.uuid4()),
        method="cash",
        amount=order.total,
    )


def _fulfillment(*, organization, order, manager, status, method=Fulfillment.Method.DELIVERY):
    values = {
        "organization": organization,
        "order": order,
        "sequence": 1,
        "method": method,
        "status": status,
        "created_by": manager,
    }
    now = timezone.now()
    if status in {
        Fulfillment.Status.PREPARING,
        Fulfillment.Status.READY,
        Fulfillment.Status.IN_TRANSIT,
        Fulfillment.Status.COMPLETED,
    }:
        values["preparing_at"] = now
    if status in {Fulfillment.Status.READY, Fulfillment.Status.IN_TRANSIT, Fulfillment.Status.COMPLETED}:
        values["ready_at"] = now
    if status in {Fulfillment.Status.IN_TRANSIT, Fulfillment.Status.COMPLETED}:
        values["dispatched_at"] = now
    if status == Fulfillment.Status.COMPLETED:
        values["completed_at"] = now
    if method == Fulfillment.Method.PICKUP:
        unit = OrganizationUnit.objects.create(organization=organization, name=f"Balcão {status}")
        values.update(
            pickup_unit=unit,
            pickup_unit_name_snapshot=unit.name,
            destination_snapshot={},
        )
    return Fulfillment.objects.create(**values)


def test_confirmed_order_without_payment_recommends_payment(
    organization,
    payable_order,
    manager,
    manager_membership,
):
    action = order_next_action(organization=organization, order=payable_order, user=manager)

    assert action["kind"] == "create_payment"
    assert action["can_operate"] is True


def test_draft_cancelled_and_cross_org_orders_have_closed_or_no_action(
    organization,
    other_organization,
    payable_order,
    manager,
):
    payable_order.status = Order.Status.DRAFT
    assert order_next_action(organization=organization, order=payable_order, user=manager)["kind"] == "confirm_order"
    payable_order.status = Order.Status.CANCELLED
    assert order_next_action(organization=organization, order=payable_order, user=manager)["kind"] == "closed"
    assert order_next_action(organization=other_organization, order=payable_order, user=manager) is None


def test_pending_payment_exposes_only_same_organization_pix(
    organization,
    payable_order,
    manager,
    manager_membership,
):
    payment = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    pix = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.RANDOM,
        key_value="123e4567-e89b-12d3-a456-426614174000",
        beneficiary_name="Loja Exemplo",
    )

    action = order_next_action(organization=organization, order=payable_order, user=manager)

    assert action["kind"] == "payment_pending"
    assert action["payment"] == payment
    assert action["pix"] == pix


def test_payment_attention_and_closed_states_are_guided(
    organization,
    payable_order,
    manager,
    manager_membership,
):
    payment = PaymentIntent.objects.create(
        organization=organization,
        order=payable_order,
        status=PaymentIntent.Status.REQUIRES_ATTENTION,
        amount=payable_order.total,
        order_number_snapshot=payable_order.display_number,
        customer_name_snapshot=payable_order.customer_name_snapshot,
        created_by=manager,
        attention_code="manual_review",
    )
    action = order_next_action(organization=organization, order=payable_order, user=manager)
    assert action["kind"] == "payment_attention"

    payment.status = PaymentIntent.Status.EXPIRED
    payment.attention_code = ""
    payment.expired_at = timezone.now()
    payment.save(update_fields=("status", "attention_code", "expired_at", "updated_at"))
    action = order_next_action(organization=organization, order=payable_order, user=manager)
    assert action["kind"] == "payment_closed"


def test_paid_order_recommends_fulfillment_without_mutating_order(
    organization,
    payable_order,
    manager,
    manager_membership,
):
    _paid_intent(organization=organization, order=payable_order, manager=manager)
    payable_order.refresh_from_db()

    action = order_next_action(organization=organization, order=payable_order, user=manager)

    assert action["kind"] == "create_fulfillment"
    assert payable_order.status == payable_order.Status.CONFIRMED


@pytest.mark.parametrize(
    ("status", "expected_target", "expected_label"),
    [
        (Fulfillment.Status.DRAFT, Fulfillment.Status.PREPARING, "Iniciar preparação"),
        (Fulfillment.Status.PREPARING, Fulfillment.Status.READY, "Marcar como pronto"),
        (Fulfillment.Status.READY, Fulfillment.Status.IN_TRANSIT, "Marcar como enviado"),
        (Fulfillment.Status.IN_TRANSIT, Fulfillment.Status.COMPLETED, "Confirmar entrega"),
    ],
)
def test_delivery_fulfillment_next_transitions(
    organization,
    payable_order,
    manager,
    manager_membership,
    status,
    expected_target,
    expected_label,
):
    _paid_intent(organization=organization, order=payable_order, manager=manager)
    fulfillment = _fulfillment(
        organization=organization,
        order=payable_order,
        manager=manager,
        status=status,
    )

    action = order_next_action(organization=organization, order=payable_order, user=manager)

    assert action["kind"] == "fulfillment_transition"
    assert action["fulfillment"] == fulfillment
    assert action["target_status"] == expected_target
    assert action["label"] == expected_label


def test_pickup_preparing_and_ready_require_release_then_validation(
    organization,
    payable_order,
    manager,
    manager_membership,
    user,
    operator_membership,
):
    _paid_intent(organization=organization, order=payable_order, manager=manager)
    fulfillment = _fulfillment(
        organization=organization,
        order=payable_order,
        manager=manager,
        status=Fulfillment.Status.PREPARING,
        method=Fulfillment.Method.PICKUP,
    )
    action = order_next_action(organization=organization, order=payable_order, user=manager)
    assert action["target_status"] == Fulfillment.Status.READY
    assert action["label"] == "Liberar para retirada"

    fulfillment.status = Fulfillment.Status.READY
    fulfillment.ready_at = timezone.now()
    fulfillment.save(update_fields=("status", "ready_at", "updated_at"))
    manager_action = order_next_action(organization=organization, order=payable_order, user=manager)
    operator_action = order_next_action(organization=organization, order=payable_order, user=user)

    assert manager_action["kind"] == "pickup_validation"
    assert manager_action["pickup_code"] is not None
    assert len(manager_action["pickup_code"]) == 6
    assert operator_action["kind"] == "pickup_validation"
    assert operator_action["pickup_code"] is None


def test_completed_fulfillment_is_ignored_and_new_fulfillment_is_recommended(
    organization,
    payable_order,
    manager,
    manager_membership,
):
    _paid_intent(organization=organization, order=payable_order, manager=manager)
    _fulfillment(
        organization=organization,
        order=payable_order,
        manager=manager,
        status=Fulfillment.Status.COMPLETED,
    )
    action = order_next_action(organization=organization, order=payable_order, user=manager)
    assert action["kind"] == "create_fulfillment"
