import uuid

import pytest
from django.urls import reverse

from apps.payments.models import PaymentAttempt, PaymentIntent, PixPaymentInstruction
from apps.payments.services import create_payment_intent

pytestmark = pytest.mark.django_db


def test_manager_prepares_payment_inside_order_and_returns_to_workspace(
    client,
    organization,
    payable_order,
    manager,
    manager_membership,
):
    client.force_login(manager)

    response = client.post(
        reverse("payments:workspace_create", args=(payable_order.id,)),
        {"idempotency_key": str(uuid.uuid4())},
    )

    assert response.status_code == 302
    assert response.url == reverse("orders:detail", args=(payable_order.id,))
    intent = PaymentIntent.objects.get(order=payable_order)
    assert intent.amount == payable_order.total
    assert intent.order_number_snapshot == payable_order.display_number


def test_operator_cannot_prepare_payment_from_order_workspace(
    client,
    payable_order,
    user,
    operator_membership,
):
    client.force_login(user)

    response = client.post(
        reverse("payments:workspace_create", args=(payable_order.id,)),
        {"idempotency_key": str(uuid.uuid4())},
    )

    assert response.status_code == 404
    assert not PaymentIntent.objects.filter(order=payable_order).exists()


def test_manager_confirms_manual_payment_without_leaving_order(
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
        reverse("payments:workspace_manual", args=(intent.id,)),
        {
            "method": "pix",
            "amount": str(intent.amount),
            "expected_version": intent.version,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("orders:detail", args=(payable_order.id,))
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.PAID


def test_order_workspace_renders_pix_and_active_checkout_actions(
    client,
    organization,
    payable_order,
    manager,
    manager_membership,
    mercado_account,
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    PixPaymentInstruction.objects.create(
        organization=organization,
        key_type="random",
        key_value="123e4567-e89b-12d3-a456-426614174000",
        beneficiary_name="Loja Exemplo",
        bank_name="Banco Exemplo",
        is_active=True,
    )
    hosted_url = "https://checkout.example.test/pay/workspace"
    PaymentAttempt.objects.create(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        provider=mercado_account.provider,
        status=PaymentAttempt.Status.ACTIVE,
        provider_idempotency_key=str(uuid.uuid4()),
        hosted_url=hosted_url,
    )
    client.force_login(manager)

    response = client.get(reverse("orders:detail", args=(payable_order.id,)))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'id="payment-workspace"' in html
    assert "123e4567-e89b-12d3-a456-426614174000" in html
    assert "Copiar PIX" in html
    assert hosted_url in html
    assert "Copiar link" in html
    assert reverse("payments:detail", args=(intent.id,)) not in html


def test_checkout_request_from_workspace_uses_payments_service_and_returns_to_order(
    client,
    organization,
    payable_order,
    manager,
    manager_membership,
    mercado_account,
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    client.force_login(manager)

    response = client.post(
        reverse("payments:workspace_checkout", args=(intent.id,)),
        {
            "provider_account": str(mercado_account.id),
            "expected_version": intent.version,
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("orders:detail", args=(payable_order.id,))
    attempt = PaymentAttempt.objects.get(intent=intent)
    assert attempt.status == PaymentAttempt.Status.REQUESTED
    assert attempt.hosted_url == ""
