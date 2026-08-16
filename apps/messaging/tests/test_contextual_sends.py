import uuid
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.fulfillment.models import Fulfillment
from apps.messaging import contextual, services
from apps.messaging.exceptions import InvalidMessage
from apps.messaging.models import Message, MessageTemplate, MessagingChannel, MessagingPreference
from apps.payments.models import PaymentIntent, PixPaymentInstruction

pytestmark = pytest.mark.django_db


def _key():
    return str(uuid.uuid4())


def _template(*, organization, semantic_key, purpose):
    if semantic_key == "pix_instruction":
        body = (
            "Olá {customer_name}, para pagar o pedido {order_number} via PIX use "
            "{pix_key_type}: {pix_key}. Beneficiário: {pix_beneficiary}. Banco: {pix_bank}."
        )
        schema = [
            "customer_name",
            "order_number",
            "pix_key_type",
            "pix_key",
            "pix_beneficiary",
            "pix_bank",
        ]
    else:
        body = (
            "Olá {customer_name}, o pedido {order_number} foi enviado. "
            "Rastreio: {tracking_code} {tracking_url}"
        )
        schema = ["customer_name", "order_number", "tracking_code", "tracking_url"]
    return MessageTemplate.objects.create(
        organization=organization,
        semantic_key=semantic_key,
        name=semantic_key,
        channel=MessageTemplate.Channel.WHATSAPP,
        locale="pt-BR",
        version=1,
        body_text=body,
        parameter_schema=schema,
        is_active=True,
    )


def _preference(*, organization, contact, purpose):
    return MessagingPreference.objects.create(
        organization=organization,
        contact_point=contact,
        channel=MessagingChannel.Kind.WHATSAPP,
        purpose=purpose,
        decision=MessagingPreference.Decision.ALLOWED,
        provenance="consent_record",
        policy_version=1,
        effective_at=timezone.now(),
        is_active=True,
    )


def _payment(*, organization, order, actor):
    return PaymentIntent.objects.create(
        organization=organization,
        order=order,
        status=PaymentIntent.Status.PENDING,
        currency="BRL",
        amount=Decimal("200.00"),
        order_number_snapshot=order.display_number,
        customer_name_snapshot=order.customer_name_snapshot,
        created_by=actor,
    )


def _pix(*, organization, actor, key_value="pix@example.com"):
    return PixPaymentInstruction.objects.create(
        organization=organization,
        key_type=PixPaymentInstruction.KeyType.EMAIL,
        key_value=key_value,
        beneficiary_name="Vidalys Teste",
        bank_name="Banco Teste",
        is_active=True,
        updated_by=actor,
    )


def test_operator_cannot_open_pix_contextual_send(
    client,
    organization,
    user,
    operator_membership,
    messaging_order,
):
    intent = _payment(organization=organization, order=messaging_order, actor=user)
    client.force_login(user)

    response = client.get(reverse("messaging:contextual_send", args=("pix", intent.id)))

    assert response.status_code == 404
    assert not Message.objects.filter(purpose=contextual.PURPOSE_PIX_INSTRUCTION).exists()


def test_manager_registers_pix_message_without_mutating_payment(
    client,
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_channel,
):
    _, contact = messaging_customer
    intent = _payment(organization=organization, order=messaging_order, actor=manager)
    _pix(organization=organization, actor=manager)
    _template(organization=organization, semantic_key="pix_instruction", purpose="pix_instruction")
    _preference(organization=organization, contact=contact, purpose="pix_instruction")
    original_status = intent.status
    original_version = intent.version
    client.force_login(manager)

    response = client.post(
        reverse("messaging:contextual_send", args=("pix", intent.id)),
        {
            "channel": whatsapp_channel.id,
            "contact_point": contact.id,
            "idempotency_key": _key(),
        },
    )

    assert response.status_code == 302
    message = Message.objects.get(purpose="pix_instruction", source_id=intent.id)
    assert message.status == Message.Status.PENDING
    intent.refresh_from_db()
    assert intent.status == original_status
    assert intent.version == original_version


def test_pix_message_fails_closed_when_pix_configuration_changes(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_channel,
):
    _, contact = messaging_customer
    intent = _payment(organization=organization, order=messaging_order, actor=manager)
    pix = _pix(organization=organization, actor=manager)
    _template(organization=organization, semantic_key="pix_instruction", purpose="pix_instruction")
    _preference(organization=organization, contact=contact, purpose="pix_instruction")
    message = contextual.create_pix_message(
        organization=organization,
        actor=manager,
        intent=intent,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=_key(),
    )
    attempt = message.attempts.get()
    message, attempt = services.claim_dispatch(attempt_id=attempt.id)
    pix.key_value = "novo-pix@example.com"
    pix.save(update_fields=("key_value", "updated_at"))

    with pytest.raises(InvalidMessage, match="Configuração PIX mudou"):
        contextual.prepare_pix_send_request(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
        )


def test_operator_registers_tracking_message_without_mutating_fulfillment(
    client,
    organization,
    user,
    operator_membership,
    messaging_order,
    messaging_customer,
    whatsapp_channel,
):
    _, contact = messaging_customer
    fulfillment = Fulfillment.objects.create(
        organization=organization,
        order=messaging_order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        status=Fulfillment.Status.READY,
        destination_snapshot={"city": "São Paulo", "state": "SP"},
        tracking_code="BR123456789",
        tracking_url="https://tracking.example.test/BR123456789",
        created_by=user,
        ready_at=timezone.now(),
    )
    _template(
        organization=organization,
        semantic_key="fulfillment_tracking",
        purpose=services.PURPOSE_FULFILLMENT_PROGRESS,
    )
    _preference(
        organization=organization,
        contact=contact,
        purpose=services.PURPOSE_FULFILLMENT_PROGRESS,
    )
    original_status = fulfillment.status
    original_version = fulfillment.version
    client.force_login(user)

    response = client.post(
        reverse("messaging:contextual_send", args=("tracking", fulfillment.id)),
        {
            "channel": whatsapp_channel.id,
            "contact_point": contact.id,
            "idempotency_key": _key(),
        },
    )

    assert response.status_code == 302
    message = Message.objects.get(
        purpose=services.PURPOSE_FULFILLMENT_PROGRESS,
        source_id=fulfillment.id,
        template_semantic_key="fulfillment_tracking",
    )
    assert message.parameter_snapshot["tracking_code"] == "BR123456789"
    fulfillment.refresh_from_db()
    assert fulfillment.status == original_status
    assert fulfillment.version == original_version
