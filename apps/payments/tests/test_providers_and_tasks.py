import uuid
from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.exceptions import InvalidPayment, ProviderEffectsDisabled
from apps.payments.models import PaymentIntent
from apps.payments.providers import (
    CheckoutResult,
    DisabledProviderAdapter,
    MercadoPagoCheckoutProAdapter,
    PagarmePaymentLinkAdapter,
    amount_to_minor_units,
    build_checkout_request,
    map_provider_status,
)
from apps.payments.services import (
    create_payment_intent,
    dispatch_requested_checkout,
    request_hosted_checkout,
)
from apps.payments.tasks import consume_order_cancellations
from apps.platform.services import enqueue_event


def key():
    return str(uuid.uuid4())


def test_provider_contract_mapping_and_disabled_network():
    assert amount_to_minor_units("10.23") == 1023
    assert map_provider_status(provider="mercado_pago", status="approved") == "paid"
    assert map_provider_status(provider="pagarme", status="processing") == "processing"
    with pytest.raises(InvalidPayment, match="desconhecido"):
        map_provider_status(provider="mercado_pago", status="future_state")
    with pytest.raises(ProviderEffectsDisabled):
        DisabledProviderAdapter().create_checkout(object())


@pytest.mark.django_db
def test_provider_payload_contracts_and_fake_dispatch(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    request = build_checkout_request(intent=intent, idempotency_key=key())
    mercado_payload = MercadoPagoCheckoutProAdapter.contract_payload(request)
    pagarme_payload = PagarmePaymentLinkAdapter.contract_payload(request)
    assert mercado_payload["external_reference"] == str(intent.id)
    assert mercado_payload["items"][0]["unit_price"] == Decimal("125.40")
    assert pagarme_payload["items"][0]["amount"] == 12540
    assert set(pagarme_payload["payment_settings"]["accepted_payment_methods"]) == {
        "credit_card",
        "pix",
        "boleto",
    }
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )

    class FakeMercadoAdapter:
        provider = "mercado_pago"
        external = False

        def create_checkout(self, checkout_request):
            assert checkout_request.amount_minor == 12540
            return CheckoutResult("fake-resource", "https://checkout.example.test/fake")

    dispatched = dispatch_requested_checkout(
        attempt=attempt,
        adapter=FakeMercadoAdapter(),
        idempotency_key=key(),
    )
    assert dispatched.status == "active"


@pytest.mark.django_db
def test_order_cancellation_consumer_is_idempotent(organization, payable_order, manager, manager_membership):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    payable_order.status = Order.Status.CANCELLED
    payable_order.cancelled_at = payable_order.confirmed_at
    payable_order.cancel_reason = "Cancelamento comercial"
    payable_order.save(update_fields=("status", "cancelled_at", "cancel_reason"))
    event = enqueue_event(
        organization=organization,
        event_type="order.cancelled",
        aggregate_type="order",
        aggregate_id=payable_order.id,
        payload={"order_id": str(payable_order.id), "status": "cancelled"},
        idempotency_key=f"task-test-{payable_order.id}",
    )
    assert consume_order_cancellations() == 1
    assert consume_order_cancellations() == 0
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.CANCELLED
    assert intent.command_receipts.get(source_event_id=event.id).completed
