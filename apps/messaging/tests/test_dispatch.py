import pytest
from django.utils import timezone

from apps.messaging import services
from apps.messaging.exceptions import InvalidMessage, ProviderEffectsDisabled
from apps.messaging.models import Message, MessageDeliveryAttempt
from apps.messaging.providers import SendResult
from apps.messaging.tests.conftest import key
from apps.payments.models import PaymentIntent

pytestmark = pytest.mark.django_db


def _fake_adapter(provider, result=None, error=None, external=False):
    class FakeAdapter:
        def send_text(self, request):
            if error is not None:
                raise error
            return result or SendResult("external-message-id", True)

    adapter = FakeAdapter()
    adapter.provider = provider
    adapter.external = external
    return adapter


def _create_message(
    organization, actor, messaging_order, messaging_customer, whatsapp_template, whatsapp_channel, allowed_preference
):
    _, contact = messaging_customer
    return services.create_message_from_command(
        organization=organization,
        actor=actor,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )


def test_dispatch_sets_message_sent(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    attempt = message.attempts.get()
    dispatched = services.dispatch_message(
        attempt=attempt,
        adapter=_fake_adapter("evolution"),
        idempotency_key=key(),
    )
    assert dispatched.status == Message.Status.SENT
    assert dispatched.sent_at is not None
    attempt.refresh_from_db()
    assert attempt.status == MessageDeliveryAttempt.Status.ACCEPTED
    assert attempt.external_message_id == "external-message-id"
    assert attempt.dispatch_lease_token is None


def test_dispatch_timeout_becomes_uncertain_without_retry(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    attempt = message.attempts.get()
    dispatched = services.dispatch_message(
        attempt=attempt,
        adapter=_fake_adapter("evolution", error=TimeoutError("lost after accept")),
        idempotency_key=key(),
    )
    assert dispatched.status == Message.Status.UNCERTAIN
    attempt.refresh_from_db()
    assert attempt.status == MessageDeliveryAttempt.Status.UNCERTAIN
    assert attempt.dispatch_attempts == 1
    assert attempt.dispatch_available_at is None


def test_dispatch_disabled_adapter_keeps_message_pending(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    attempt = message.attempts.get()
    with pytest.raises(ProviderEffectsDisabled):
        services.dispatch_message(
            attempt=attempt,
            adapter=_fake_adapter("evolution", external=True),
            idempotency_key=key(),
        )
    message.refresh_from_db()
    assert message.status == Message.Status.PENDING


def test_dispatch_stale_checkout_link_fails_permanently(
    organization,
    manager,
    manager_membership,
    messaging_customer,
    checkout_template,
    whatsapp_channel,
    allowed_checkout_preference,
    active_checkout_intent,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.PAYMENT,
        source_id=active_checkout_intent.id,
        purpose="checkout_link",
        template=checkout_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    active_checkout_intent.status = PaymentIntent.Status.REQUIRES_ATTENTION
    active_checkout_intent.attention_code = "replaced"
    active_checkout_intent.save(update_fields=("status", "attention_code"))
    attempt = message.attempts.get()
    dispatched = services.dispatch_message(
        attempt=attempt,
        adapter=_fake_adapter("evolution"),
        idempotency_key=key(),
    )
    assert dispatched.status == Message.Status.FAILED


def test_dispatch_adapter_mismatch_releases_and_raises(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    attempt = message.attempts.get()
    with pytest.raises(InvalidMessage, match="Adapter"):
        services.dispatch_message(
            attempt=attempt,
            adapter=_fake_adapter("ses"),
            idempotency_key=key(),
        )
    message.refresh_from_db()
    assert message.status == Message.Status.PENDING


def test_claim_dispatch_leases_exclusively(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    attempt = message.attempts.get()
    claimed, _ = services.claim_dispatch(attempt_id=attempt.id)
    assert claimed.status == Message.Status.QUEUED
    with pytest.raises(InvalidMessage, match="reservada"):
        services.claim_dispatch(attempt_id=attempt.id)


def test_render_context_resolves_active_checkout_link_at_dispatch(
    organization,
    manager,
    manager_membership,
    messaging_customer,
    checkout_template,
    whatsapp_channel,
    allowed_checkout_preference,
    active_checkout_intent,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.PAYMENT,
        source_id=active_checkout_intent.id,
        purpose="checkout_link",
        template=checkout_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    assert message.parameter_snapshot.get("checkout_link") is None
    rendered = services._render_context(message=message)
    assert rendered["checkout_link"] == "https://checkout.example.test/active"


def test_single_active_attempt_constraint(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        MessageDeliveryAttempt.objects.create(
            organization=organization,
            message=message,
            channel=whatsapp_channel,
            dispatch_key="second-key",
            provider_correlation_tag="vf:second",
        )


@pytest.mark.parametrize("stale_kind", ["contact", "permission", "template", "channel", "source"])
def test_dispatch_revalidates_mutable_dependencies(
    stale_kind,
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    contact = messaging_customer[1]
    if stale_kind == "contact":
        contact.normalized_value = "+5511888887777"
        contact.save(update_fields=("normalized_value",))
    elif stale_kind == "permission":
        type(allowed_preference).objects.filter(id=allowed_preference.id).update(decision="suppressed")
    elif stale_kind == "template":
        type(whatsapp_template).objects.filter(id=whatsapp_template.id).update(is_active=False)
    elif stale_kind == "channel":
        whatsapp_channel.state = "disabled"
        whatsapp_channel.save(update_fields=("state",))
    else:
        messaging_order.version += 1
        messaging_order.save(update_fields=("version",))
    dispatched = services.dispatch_message(
        attempt=message.attempts.get(),
        adapter=_fake_adapter("evolution"),
        idempotency_key=key(),
    )
    assert dispatched.status == Message.Status.FAILED


def test_transport_loss_becomes_uncertain(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    result = services.dispatch_message(
        attempt=message.attempts.get(),
        adapter=_fake_adapter("evolution", error=ConnectionError("lost")),
        idempotency_key=key(),
    )
    assert result.status == Message.Status.UNCERTAIN


def test_provider_rejection_is_failed(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    result = services.dispatch_message(
        attempt=message.attempts.get(),
        adapter=_fake_adapter("evolution", result=SendResult("", False)),
        idempotency_key=key(),
    )
    assert result.status == Message.Status.FAILED


def test_expired_lease_before_send_is_safely_reclaimed(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    _, attempt = services.claim_dispatch(attempt_id=message.attempts.get().id)
    attempt.dispatch_lease_expires_at = timezone.now()
    attempt.save(update_fields=("dispatch_lease_expires_at",))
    result = services.dispatch_message(
        attempt=attempt,
        adapter=_fake_adapter("evolution"),
        idempotency_key=key(),
    )
    assert result.status == Message.Status.SENT


def test_expired_lease_after_send_started_becomes_uncertain(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    _, attempt = services.claim_dispatch(attempt_id=message.attempts.get().id)
    services.mark_sending(attempt_id=attempt.id, lease_token=attempt.dispatch_lease_token)
    attempt.dispatch_lease_expires_at = timezone.now()
    attempt.save(update_fields=("dispatch_lease_expires_at",))
    result = services.dispatch_message(
        attempt=attempt,
        adapter=_fake_adapter("evolution"),
        idempotency_key=key(),
    )
    assert result.status == Message.Status.UNCERTAIN


def test_manager_reconciles_uncertain_message_with_verified_status(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = _create_message(
        organization,
        manager,
        messaging_order,
        messaging_customer,
        whatsapp_template,
        whatsapp_channel,
        allowed_preference,
    )
    message = services.dispatch_message(
        attempt=message.attempts.get(),
        adapter=_fake_adapter("evolution", error=TimeoutError()),
        idempotency_key=key(),
    )
    attempt = message.attempts.get()
    attempt.external_message_id = "verified-after-timeout"
    attempt.save(update_fields=("external_message_id",))

    class StatusAdapter:
        provider = "evolution"
        external = False

        def fetch_status(self, external_message_id):
            assert external_message_id == "verified-after-timeout"
            return "delivered"

    reconciled = services.reconcile_uncertain(
        organization=organization,
        actor=manager,
        message=message,
        expected_version=message.version,
        idempotency_key=key(),
        adapter=StatusAdapter(),
    )
    assert reconciled.status == Message.Status.DELIVERED
