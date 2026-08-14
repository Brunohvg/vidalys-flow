import hashlib
import json

import pytest

from apps.messaging import services
from apps.messaging.callbacks import process_delivery_callback, request_digest, verify_secret_header
from apps.messaging.exceptions import CallbackRejected, OrganizationMismatch, ProviderEffectsDisabled, UnsafeProviderUrl
from apps.messaging.models import Message, MessagingPreference, MessagingProviderConnection
from apps.messaging.tests.conftest import key

pytestmark = pytest.mark.django_db


def _secret_resolver(secret):
    def resolver(*, connection):
        return secret

    return resolver


def _signature(secret, channel_id, external_message_id, request_id):
    return secret


def _dispatched_message(
    organization,
    manager,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    external_id="external-message-id",
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )

    class FakeAdapter:
        provider = "evolution"
        external = False

        def send_text(self, request):
            from apps.messaging.providers import SendResult

            return SendResult(external_id, True)

    return services.dispatch_message(attempt=message.attempts.get(), adapter=FakeAdapter(), idempotency_key=key())


def test_callback_delivery_marks_delivered(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    evolution_connection,
):
    evolution_connection.callbacks_enabled = True
    evolution_connection.save(update_fields=("callbacks_enabled",))
    message = _dispatched_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    secret = "callback-secret"
    request_id = "req-123"
    body = json.dumps({"message_id": "external-message-id", "status": "delivered"}).encode()
    receipt = process_delivery_callback(
        channel=whatsapp_channel,
        raw_body=body,
        request_id=request_id,
        signature_header=_signature(secret, whatsapp_channel.id, "external-message-id", request_id),
        secret_resolver=_secret_resolver(secret),
    )
    message.refresh_from_db()
    assert message.status == Message.Status.DELIVERED
    assert message.delivered_at is not None
    assert receipt.canonical_result == "delivered"


def test_callback_rejects_invalid_secret(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    evolution_connection,
):
    evolution_connection.callbacks_enabled = True
    evolution_connection.save(update_fields=("callbacks_enabled",))
    _dispatched_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    request_id = "req-123"
    body = json.dumps({"message_id": "external-message-id", "status": "delivered"}).encode()
    with pytest.raises(CallbackRejected, match="inválido"):
        process_delivery_callback(
            channel=whatsapp_channel,
            raw_body=body,
            request_id=request_id,
            signature_header="wrong-signature",
            secret_resolver=_secret_resolver("callback-secret"),
        )


def test_callback_rejects_disabled_connection(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    evolution_connection,
):
    _dispatched_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    body = json.dumps({"message_id": "external-message-id", "status": "delivered"}).encode()
    with pytest.raises(CallbackRejected, match="desabilitado"):
        process_delivery_callback(
            channel=whatsapp_channel,
            raw_body=body,
            request_id="req-123",
            signature_header="x",
            secret_resolver=_secret_resolver("callback-secret"),
        )


def test_callback_rejects_malformed_body(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    evolution_connection,
):
    evolution_connection.callbacks_enabled = True
    evolution_connection.save(update_fields=("callbacks_enabled",))
    _dispatched_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    with pytest.raises(CallbackRejected, match="malformado"):
        process_delivery_callback(
            channel=whatsapp_channel,
            raw_body=b"not-json",
            request_id="req-123",
            signature_header="x",
            secret_resolver=_secret_resolver("callback-secret"),
        )


def test_callback_rejects_oversized_body(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    evolution_connection,
):
    evolution_connection.callbacks_enabled = True
    evolution_connection.save(update_fields=("callbacks_enabled",))
    _dispatched_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    with pytest.raises(CallbackRejected, match="limite"):
        process_delivery_callback(
            channel=whatsapp_channel,
            raw_body=b"x" * (64 * 1024 + 1),
            request_id="req-123",
            signature_header="x",
            secret_resolver=_secret_resolver("callback-secret"),
        )


def test_callback_is_deduplicated_and_monotonic(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    evolution_connection,
):
    evolution_connection.callbacks_enabled = True
    evolution_connection.save(update_fields=("callbacks_enabled",))
    _dispatched_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    secret = "callback-secret"
    request_id = "req-123"
    body = json.dumps({"message_id": "external-message-id", "status": "delivered"}).encode()
    signature = _signature(secret, whatsapp_channel.id, "external-message-id", request_id)
    first = process_delivery_callback(
        channel=whatsapp_channel,
        raw_body=body,
        request_id=request_id,
        signature_header=signature,
        secret_resolver=_secret_resolver(secret),
    )
    second = process_delivery_callback(
        channel=whatsapp_channel,
        raw_body=body,
        request_id=request_id,
        signature_header=signature,
        secret_resolver=_secret_resolver(secret),
    )
    assert first.id == second.id
    message = Message.objects.get()
    assert message.status == Message.Status.DELIVERED


def test_late_failure_evidence_does_not_regress_delivered(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    evolution_connection,
):
    evolution_connection.callbacks_enabled = True
    evolution_connection.save(update_fields=("callbacks_enabled",))
    _dispatched_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    secret = "callback-secret"
    delivered = process_delivery_callback(
        channel=whatsapp_channel,
        raw_body=json.dumps({"message_id": "external-message-id", "status": "delivered"}).encode(),
        request_id="req-delivered",
        signature_header=_signature(secret, whatsapp_channel.id, "external-message-id", "req-delivered"),
        secret_resolver=_secret_resolver(secret),
    )
    failed = process_delivery_callback(
        channel=whatsapp_channel,
        raw_body=json.dumps({"message_id": "external-message-id", "status": "failed"}).encode(),
        request_id="req-failed",
        signature_header=_signature(secret, whatsapp_channel.id, "external-message-id", "req-failed"),
        secret_resolver=_secret_resolver(secret),
    )
    assert delivered.canonical_result == "delivered"
    assert failed.canonical_result == "delivered"
    assert failed.has_inconsistency
    assert failed.reason_code == "late_failure_evidence"
    assert Message.objects.get().status == Message.Status.DELIVERED


def test_callback_cross_channel_rejected(
    organization,
    other_organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    evolution_connection,
):
    evolution_connection.callbacks_enabled = True
    evolution_connection.save(update_fields=("callbacks_enabled",))
    _dispatched_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    foreign_connection = MessagingProviderConnection.objects.create(
        organization=other_organization,
        provider="evolution",
        mode="linked_device",
        display_name="Estrangeira",
        credential_alias="foreign-alias",
        is_active=True,
        callbacks_enabled=True,
    )
    from apps.messaging.models import MessagingChannel

    foreign_channel = MessagingChannel.objects.create(
        organization=other_organization,
        connection=foreign_connection,
        kind=MessagingChannel.Kind.WHATSAPP,
        display_name="Estrangeiro",
        state=MessagingChannel.State.ACTIVE,
    )
    with pytest.raises(OrganizationMismatch):
        process_delivery_callback(
            channel=foreign_channel,
            raw_body=json.dumps({"message_id": "external-message-id", "status": "delivered"}).encode(),
            request_id="req-123",
            signature_header=_signature("callback-secret", foreign_channel.id, "external-message-id", "req-123"),
            secret_resolver=_secret_resolver("callback-secret"),
        )


def test_ses_callback_remains_fail_closed_until_sns_authenticity_exists(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    ses_connection,
    email_channel,
):
    ses_connection.callbacks_enabled = True
    ses_connection.save(update_fields=("callbacks_enabled",))
    email = messaging_customer[0].contacts.get(kind="email")
    from apps.messaging.models import MessageTemplate

    template = MessageTemplate.objects.create(
        organization=organization,
        semantic_key="email_order_confirmation",
        name="Confirmação por e-mail",
        channel=MessageTemplate.Channel.EMAIL,
        locale="pt-BR",
        version=1,
        body_text="Olá {customer_name}, pedido {order_number}.",
        parameter_schema=["customer_name", "order_number"],
        is_active=True,
    )
    MessagingPreference.objects.create(
        organization=organization,
        contact_point=email,
        channel="email",
        purpose="order_confirmation",
        decision=MessagingPreference.Decision.ALLOWED,
        provenance="consent_record",
        policy_version=1,
        effective_at=email.created_at,
        is_active=True,
    )
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=template,
        channel=email_channel,
        contact_point=email,
        idempotency_key=key(),
    )

    class FakeSesAdapter:
        provider = "ses"
        external = False

        def send_text(self, request):
            from apps.messaging.providers import SendResult

            return SendResult("ses-message-id", True)

    services.dispatch_message(attempt=message.attempts.get(), adapter=FakeSesAdapter(), idempotency_key=key())
    secret = "ses-secret"
    with pytest.raises(ProviderEffectsDisabled):
        process_delivery_callback(
            channel=email_channel,
            raw_body=json.dumps({"message_id": "ses-message-id", "status": "bounce"}).encode(),
            request_id="req-bounce",
            signature_header=_signature(secret, email_channel.id, "ses-message-id", "req-bounce"),
            secret_resolver=_secret_resolver(secret),
        )


def test_request_digest_and_secret_header_helpers():
    assert request_digest(b"abc") == hashlib.sha256(b"abc").hexdigest()
    with pytest.raises(CallbackRejected):
        verify_secret_header(signature_header="", secret="s")
    with pytest.raises(UnsafeProviderUrl):
        from apps.messaging.providers import map_delivery_status

        map_delivery_status(provider="evolution", status="unknown")
