import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from apps.orders.models import Order
from apps.payments.exceptions import InvalidPayment, ProviderEffectsDisabled
from apps.payments.models import PaymentAttempt, PaymentIntent
from apps.payments.providers import (
    CheckoutRequest,
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
from apps.payments.tasks import consume_order_cancellations, dispatch_checkout_events
from apps.platform.services import enqueue_event
from config.celery import app as celery_app


def test_payment_tasks_are_registered_by_celery():
    celery_app.loader.import_default_modules()

    assert {
        "apps.payments.tasks.consume_order_cancellations",
        "apps.payments.tasks.dispatch_checkout_requests",
        "apps.payments.tasks.dispatch_checkout_cancellations",
    } <= set(celery_app.tasks)


def test_payment_dispatch_tasks_have_isolated_integration_routes():
    queues = {queue.name: queue for queue in settings.CELERY_TASK_QUEUES}

    assert queues["default"].routing_key == "default"
    assert queues["integrations"].routing_key == "integrations"
    assert queues["default"].exchange.name == queues["integrations"].exchange.name == "vidalys"
    assert settings.CELERY_TASK_ROUTES["apps.payments.tasks.dispatch_checkout_requests"] == {
        "queue": "integrations"
    }
    assert settings.CELERY_TASK_ROUTES["apps.payments.tasks.dispatch_checkout_cancellations"] == {
        "queue": "integrations"
    }


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
    assert pagarme_payload["cart_settings"]["items"][0]["amount"] == 12540
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


@pytest.mark.parametrize(
    ("fixture_name", "adapter_class"),
    [
        ("mercado_pago_checkout_pro.json", MercadoPagoCheckoutProAdapter),
        ("pagarme_payment_link_v5.json", PagarmePaymentLinkAdapter),
    ],
)
def test_provider_builders_match_versioned_official_contract_fixtures(fixture_name, adapter_class):
    fixture_path = Path(__file__).parent / "fixtures" / fixture_name
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    request = CheckoutRequest(**fixture["request"])
    payload = adapter_class.contract_payload(request)
    if adapter_class is MercadoPagoCheckoutProAdapter:
        payload["items"][0]["unit_price"] = str(payload["items"][0]["unit_price"])
    assert payload == fixture["expected_payload"]
    assert fixture["source"].startswith("https://")


@pytest.mark.django_db
def test_timeout_after_remote_success_reuses_attempt_and_provider_idempotency_key(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=key(),
    )
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    remote_resources = {}
    observed_keys = []

    class TimeoutThenRecoverAdapter:
        provider = "mercado_pago"
        external = False

        def __init__(self, timeout):
            self.timeout = timeout

        def create_checkout(self, checkout_request):
            observed_keys.append(checkout_request.idempotency_key)
            result = remote_resources.setdefault(
                checkout_request.idempotency_key,
                CheckoutResult("remote-created-on-timeout", "https://checkout.example.test/recovered"),
            )
            if self.timeout:
                raise TimeoutError("response lost after provider success")
            return result

    with pytest.raises(TimeoutError):
        dispatch_requested_checkout(
            attempt=attempt,
            adapter=TimeoutThenRecoverAdapter(timeout=True),
            idempotency_key=key(),
        )
    attempt.refresh_from_db()
    assert attempt.status == "requested"
    assert attempt.dispatch_lease_token is None
    assert attempt.dispatch_error_code == "timeout"
    assert attempt.dispatch_available_at is not None
    PaymentAttempt.objects.filter(id=attempt.id).update(dispatch_available_at=None)

    recovered = dispatch_requested_checkout(
        attempt=attempt,
        adapter=TimeoutThenRecoverAdapter(timeout=False),
        idempotency_key=key(),
    )
    assert recovered.status == "active"
    assert observed_keys == [attempt.provider_idempotency_key, attempt.provider_idempotency_key]
    assert intent.attempts.count() == 1
    assert recovered.dispatch_attempts == 2


@pytest.mark.django_db
def test_outbox_checkout_consumer_dispatches_requested_attempt(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=key(),
    )
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )

    class FakeAdapter:
        provider = "mercado_pago"
        external = False

        def create_checkout(self, checkout_request):
            return CheckoutResult("worker-resource", "https://checkout.example.test/worker")

    assert dispatch_checkout_events(adapter_resolver=lambda current: FakeAdapter()) == 1
    attempt.refresh_from_db()
    assert attempt.status == "active"
    assert dispatch_checkout_events(adapter_resolver=lambda current: FakeAdapter()) == 0


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
