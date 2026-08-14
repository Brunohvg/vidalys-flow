import socket
import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.customers.models import ContactPoint, Customer
from apps.messaging.models import (
    MessageAutomationRule,
    MessageTemplate,
    MessagingChannel,
    MessagingPreference,
    MessagingProviderConnection,
)
from apps.orders.models import Order
from apps.payments.models import PaymentAttempt, PaymentIntent, PaymentProviderAccount


@pytest.fixture(autouse=True)
def block_provider_network(monkeypatch):
    original = socket.getaddrinfo
    blocked_suffixes = (
        "evolutionfoundation.com.br",
        "whatsapp",
        "facebook.com",
        "amazonaws.com",
        "sns",
    )

    def guarded_getaddrinfo(host, *args, **kwargs):
        normalized = host.decode() if isinstance(host, bytes) else str(host)
        if normalized.lower().rstrip(".").endswith(blocked_suffixes):
            raise AssertionError("Provider network is forbidden in the Messaging test suite.")
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


def key():
    return str(uuid.uuid4())


@pytest.fixture
def messaging_customer(organization):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente Messaging",
    )
    whatsapp = ContactPoint.objects.create(
        customer=customer,
        kind=ContactPoint.Kind.WHATSAPP,
        value="+5511999998888",
        normalized_value="+5511999998888",
        is_primary=True,
        is_verified=True,
        is_active=True,
    )
    ContactPoint.objects.create(
        customer=customer,
        kind=ContactPoint.Kind.EMAIL,
        value="cliente@example.com",
        normalized_value="cliente@example.com",
        is_primary=True,
        is_verified=True,
        is_active=True,
    )
    return customer, whatsapp


@pytest.fixture
def messaging_order(organization, messaging_customer, manager):
    customer, _ = messaging_customer
    return Order.objects.create(
        organization=organization,
        number=51,
        customer=customer,
        status=Order.Status.CONFIRMED,
        currency="BRL",
        subtotal=Decimal("200.00"),
        total=Decimal("200.00"),
        customer_name_snapshot=customer.display_name,
        created_by=manager,
        confirmed_at=timezone.now(),
    )


@pytest.fixture
def evolution_connection(organization):
    return MessagingProviderConnection.objects.create(
        organization=organization,
        provider=MessagingProviderConnection.Provider.EVOLUTION,
        mode=MessagingProviderConnection.Mode.LINKED_DEVICE,
        display_name="Evolution principal",
        credential_alias=f"msg-evolution-{uuid.uuid4()}",
        webhook_secret_alias=f"msg-wh-evolution-{uuid.uuid4()}",
        capability_snapshot=[
            "linked_device_pairing",
            "send_text",
            "delivery_receipts",
            "message_status_query",
            "multiple_channels",
        ],
        is_active=True,
    )


@pytest.fixture
def ses_connection(organization):
    return MessagingProviderConnection.objects.create(
        organization=organization,
        provider=MessagingProviderConnection.Provider.SES,
        mode=MessagingProviderConnection.Mode.EMAIL,
        display_name="SES principal",
        credential_alias=f"msg-ses-{uuid.uuid4()}",
        capability_snapshot=["send_text", "delivery_receipts", "multiple_channels", "webhook_signature"],
        is_active=True,
    )


@pytest.fixture
def whatsapp_channel(organization, evolution_connection):
    return MessagingChannel.objects.create(
        organization=organization,
        connection=evolution_connection,
        kind=MessagingChannel.Kind.WHATSAPP,
        display_name="WhatsApp Oficial",
        external_channel_id="vf-whatsapp-channel",
        capability_snapshot=["linked_device_pairing", "send_text", "delivery_receipts"],
        state=MessagingChannel.State.ACTIVE,
    )


@pytest.fixture
def email_channel(organization, ses_connection):
    return MessagingChannel.objects.create(
        organization=organization,
        connection=ses_connection,
        kind=MessagingChannel.Kind.EMAIL,
        display_name="E-mail transacional",
        external_channel_id="ses-channel",
        capability_snapshot=["send_text", "delivery_receipts"],
        state=MessagingChannel.State.ACTIVE,
    )


@pytest.fixture
def whatsapp_template(organization):
    return MessageTemplate.objects.create(
        organization=organization,
        semantic_key="order_confirmation",
        name="Confirmação de pedido",
        channel=MessageTemplate.Channel.WHATSAPP,
        locale="pt-BR",
        version=1,
        body_text="Olá {customer_name}, seu pedido {order_number} foi confirmado.",
        parameter_schema=["customer_name", "order_number"],
        is_active=True,
    )


@pytest.fixture
def checkout_template(organization):
    return MessageTemplate.objects.create(
        organization=organization,
        semantic_key="checkout_link",
        name="Link de checkout",
        channel=MessageTemplate.Channel.WHATSAPP,
        locale="pt-BR",
        version=1,
        body_text="Olá {customer_name}, pague seu pedido {order_number} em {checkout_link}.",
        parameter_schema=["customer_name", "order_number", "checkout_link"],
        is_active=True,
    )


@pytest.fixture
def allowed_preference(organization, messaging_customer, whatsapp_template):
    _, contact = messaging_customer
    return MessagingPreference.objects.create(
        organization=organization,
        contact_point=contact,
        channel=MessagingChannel.Kind.WHATSAPP,
        purpose="order_confirmation",
        decision=MessagingPreference.Decision.ALLOWED,
        provenance="consent_record",
        policy_version=1,
        effective_at=timezone.now(),
        is_active=True,
    )


@pytest.fixture
def allowed_checkout_preference(organization, messaging_customer):
    _, contact = messaging_customer
    return MessagingPreference.objects.create(
        organization=organization,
        contact_point=contact,
        channel=MessagingChannel.Kind.WHATSAPP,
        purpose="checkout_link",
        decision=MessagingPreference.Decision.ALLOWED,
        provenance="consent_record",
        policy_version=1,
        effective_at=timezone.now(),
        is_active=True,
    )


@pytest.fixture
def active_checkout_intent(organization, messaging_order):
    account = PaymentProviderAccount.objects.create(
        organization=organization,
        provider=PaymentProviderAccount.Provider.MERCADO_PAGO,
        display_name="Mercado Pago testes",
        credential_alias=f"pay-{uuid.uuid4()}",
        is_active=True,
    )
    intent = PaymentIntent.objects.create(
        organization=organization,
        order=messaging_order,
        status=PaymentIntent.Status.AWAITING_PAYMENT,
        currency="BRL",
        amount=Decimal("200.00"),
        order_number_snapshot=messaging_order.display_number,
        customer_name_snapshot=messaging_order.customer_name_snapshot,
        created_by=messaging_order.created_by,
    )
    PaymentAttempt.objects.create(
        organization=organization,
        intent=intent,
        provider_account=account,
        provider=PaymentProviderAccount.Provider.MERCADO_PAGO,
        status=PaymentAttempt.Status.ACTIVE,
        provider_idempotency_key=key(),
        external_resource_id="mp-resource",
        hosted_url="https://checkout.example.test/active",
        expires_at=None,
    )
    return intent


@pytest.fixture
def enabled_order_rule(organization, whatsapp_template, whatsapp_channel):
    return MessageAutomationRule.objects.create(
        organization=organization,
        event_type="order.confirmed",
        template=whatsapp_template,
        channel=whatsapp_channel,
        purpose="order_confirmation",
        is_enabled=True,
    )
