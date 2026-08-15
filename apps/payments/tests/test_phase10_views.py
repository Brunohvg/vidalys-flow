import uuid

import pytest
from django.urls import reverse

from apps.payments.models import (
    PaymentAttempt,
    PaymentIntent,
    PaymentProviderAccount,
    PixPaymentInstruction,
)
from apps.payments.services import create_payment_intent

pytestmark = pytest.mark.django_db


def test_manager_can_confirm_manual_payment_from_http(
    client,
    organization,
    payable_order,
    manager,
    manager_membership,
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    client.force_login(manager)

    response = client.post(
        reverse("payments:confirm_manual", args=(intent.id,)),
        {
            "method": "pix",
            "amount": "125.40",
            "expected_version": intent.version,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 302
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.PAID


def test_operator_cannot_confirm_manual_payment(
    client,
    organization,
    payable_order,
    manager,
    manager_membership,
    user,
    operator_membership,
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    client.force_login(user)

    response = client.post(
        reverse("payments:confirm_manual", args=(intent.id,)),
        {
            "method": "cash",
            "amount": "125.40",
            "expected_version": intent.version,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 404
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.PENDING


def test_manager_configures_pix_and_operator_cannot_open_settings(
    client,
    organization,
    manager,
    manager_membership,
    user,
    operator_membership,
):
    client.force_login(manager)
    response = client.post(
        reverse("payments:pix_settings"),
        {
            "key_type": "random",
            "key_value": "123e4567-e89b-12d3-a456-426614174000",
            "beneficiary_name": "Loja Exemplo",
            "bank_name": "Banco Exemplo",
            "is_active": "on",
        },
    )

    assert response.status_code == 302
    instruction = PixPaymentInstruction.objects.get(organization=organization)
    assert instruction.is_active is True

    client.force_login(user)
    assert client.get(reverse("payments:pix_settings")).status_code == 404


def test_active_checkout_exposes_open_copy_and_contextual_send_actions(
    client,
    organization,
    payable_order,
    manager,
    manager_membership,
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    PaymentIntent.objects.filter(id=intent.id).update(status=PaymentIntent.Status.AWAITING_PAYMENT)
    account = PaymentProviderAccount.objects.create(
        organization=organization,
        provider=PaymentProviderAccount.Provider.MERCADO_PAGO,
        display_name="Checkout teste",
        credential_alias="test-checkout-alias",
    )
    hosted_url = "https://checkout.example.test/pay/abc123"
    PaymentAttempt.objects.create(
        organization=organization,
        intent=intent,
        provider_account=account,
        provider=account.provider,
        status=PaymentAttempt.Status.ACTIVE,
        provider_idempotency_key=str(uuid.uuid4()),
        external_resource_id="checkout-test-123",
        hosted_url=hosted_url,
    )
    client.force_login(manager)

    response = client.get(reverse("payments:detail", args=(intent.id,)))
    html = response.content.decode()

    assert response.status_code == 200
    assert hosted_url in html
    assert "Copiar link" in html
    assert "Enviar ao cliente" in html
    assert f"source_id={intent.id}" in html
    assert "purpose=checkout_link" in html
