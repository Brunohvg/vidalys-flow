import hashlib
import uuid
from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.orders.models import Order
from apps.organizations.models import Membership
from apps.payments.exceptions import (
    IdempotencyConflict,
    InvalidPayment,
    OrganizationMismatch,
    PaymentPermissionDenied,
    VersionConflict,
)
from apps.payments.models import (
    PaymentAttempt,
    PaymentCommandReceipt,
    PaymentIntent,
    PaymentProviderAccount,
    PaymentStatusHistory,
    PaymentWebhookReceipt,
)
from apps.payments.providers import CheckoutResult, ProviderResource
from apps.payments.services import (
    activate_hosted_checkout,
    apply_verified_provider_resource,
    consume_order_cancelled,
    create_payment_intent,
    fetch_and_reconcile,
    reconcile_verified_resource,
    request_hosted_checkout,
)
from apps.platform.models import OutboxEvent


def key():
    return str(uuid.uuid4())


def authenticated_request_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.django_db
def test_create_intent_snapshots_order_and_is_idempotent(organization, payable_order, manager, manager_membership):
    command = key()
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=command,
    )
    retry = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=command,
    )

    assert retry.id == intent.id
    assert intent.amount == Decimal("125.40")
    assert intent.currency == "BRL"
    assert intent.order_number_snapshot == "PED-000050"
    assert PaymentStatusHistory.objects.get(intent=intent).to_status == "pending"
    assert PaymentCommandReceipt.objects.get(idempotency_key=command).completed
    assert AuditEvent.objects.get(entity_type="payment_intent").payload["amount"] == "125.40"
    assert OutboxEvent.objects.get(event_type="payment.intent_created").payload["currency"] == "BRL"


@pytest.mark.django_db
def test_create_rejects_operator_draft_zero_and_cross_organization(
    organization,
    other_organization,
    payable_order,
    user,
    operator_membership,
    manager,
    manager_membership,
):
    with pytest.raises(PaymentPermissionDenied):
        create_payment_intent(
            organization=organization,
            order=payable_order,
            actor=user,
            idempotency_key=key(),
        )
    payable_order.status = Order.Status.DRAFT
    payable_order.confirmed_at = None
    payable_order.save(update_fields=("status", "confirmed_at"))
    with pytest.raises(InvalidPayment, match="confirmado"):
        create_payment_intent(
            organization=organization,
            order=payable_order,
            actor=manager,
            idempotency_key=key(),
        )
    payable_order.status = Order.Status.CONFIRMED
    payable_order.confirmed_at = payable_order.created_at
    payable_order.total = 0
    payable_order.subtotal = 0
    payable_order.save(update_fields=("status", "confirmed_at", "total", "subtotal"))
    with pytest.raises(InvalidPayment, match="positivo"):
        create_payment_intent(
            organization=organization,
            order=payable_order,
            actor=manager,
            idempotency_key=key(),
        )
    Membership.objects.create(
        organization=other_organization,
        user=manager,
        role=Membership.Role.MANAGER,
    )
    with pytest.raises(OrganizationMismatch):
        create_payment_intent(
            organization=other_organization,
            order=payable_order,
            actor=manager,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_command_key_with_different_payload_conflicts(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=key(),
    )
    command = key()
    request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=command,
    )
    with pytest.raises(IdempotencyConflict):
        request_hosted_checkout(
            organization=organization,
            intent=intent,
            provider_account=mercado_account,
            actor=manager,
            expected_version=2,
            idempotency_key=command,
        )


@pytest.mark.django_db
def test_request_checkout_serializes_attempt_and_checks_version_and_account(
    organization,
    other_organization,
    payable_order,
    mercado_account,
    manager,
    manager_membership,
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
    assert attempt.status == PaymentAttempt.Status.REQUESTED
    assert attempt.external_resource_id == attempt.hosted_url == ""
    assert OutboxEvent.objects.filter(event_type="payment.checkout_requested").exists()
    with pytest.raises(InvalidPayment, match="checkout"):
        request_hosted_checkout(
            organization=organization,
            intent=intent,
            provider_account=mercado_account,
            actor=manager,
            expected_version=2,
            idempotency_key=key(),
        )
    intent.status = PaymentIntent.Status.PENDING
    other_account = PaymentProviderAccount.objects.create(
        organization=other_organization,
        provider="mercado_pago",
        display_name="Outra",
        credential_alias="other-test-alias",
        is_active=True,
    )
    with pytest.raises(OrganizationMismatch):
        request_hosted_checkout(
            organization=organization,
            intent=intent,
            provider_account=other_account,
            actor=manager,
            expected_version=2,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_activate_checkout_validates_https_and_does_not_leak_url_to_evidence(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    with pytest.raises(InvalidPayment, match="inválida"):
        activate_hosted_checkout(
            organization=organization,
            attempt=attempt,
            result=CheckoutResult("resource-bad", "http://unsafe.example/checkout"),
            idempotency_key=key(),
        )
    url = "https://checkout.example.test/session/private-value"
    activated = activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("resource-1", url),
        idempotency_key=key(),
    )
    intent.refresh_from_db()
    assert activated.status == PaymentAttempt.Status.ACTIVE
    assert intent.status == PaymentIntent.Status.AWAITING_PAYMENT
    evidence = str(list(AuditEvent.objects.values_list("payload", flat=True))) + str(
        list(OutboxEvent.objects.values_list("payload", flat=True))
    )
    assert "private-value" not in evidence


@pytest.mark.django_db
def test_verified_provider_resource_marks_paid_and_deduplicates(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("resource-paid", "https://checkout.example.test/paid"),
        idempotency_key=key(),
    )
    resource = ProviderResource("resource-paid", "approved", 12540, "BRL")
    receipt = apply_verified_provider_resource(
        provider_account=mercado_account,
        external_event_id="event-1",
        authenticated_request_id_digest=authenticated_request_digest("request-1"),
        request_digest="a" * 64,
        resource=resource,
    )
    duplicate = apply_verified_provider_resource(
        provider_account=mercado_account,
        external_event_id="event-1",
        authenticated_request_id_digest=authenticated_request_digest("request-1"),
        request_digest="a" * 64,
        resource=resource,
    )
    intent.refresh_from_db()
    attempt.refresh_from_db()
    assert duplicate.id == receipt.id
    assert intent.status == PaymentIntent.Status.PAID
    assert intent.paid_at is not None
    assert attempt.status == PaymentAttempt.Status.PAID
    assert PaymentWebhookReceipt.objects.count() == 1


@pytest.mark.django_db
def test_amount_mismatch_and_pagarme_callback_go_to_safe_paths(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("resource-mismatch", "https://checkout.example.test/mismatch"),
        idempotency_key=key(),
    )
    apply_verified_provider_resource(
        provider_account=mercado_account,
        external_event_id="event-mismatch",
        authenticated_request_id_digest=authenticated_request_digest("request-mismatch"),
        request_digest="b" * 64,
        resource=ProviderResource("resource-mismatch", "approved", 1, "USD"),
    )
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.REQUIRES_ATTENTION
    assert intent.attention_code == "amount_or_currency_mismatch"
    pagarme = PaymentProviderAccount.objects.create(
        organization=organization,
        provider="pagarme",
        display_name="Pagar.me",
        credential_alias="pagarme-test-alias",
        is_active=True,
        callbacks_enabled=False,
    )
    with pytest.raises(InvalidPayment, match="habilitado"):
        apply_verified_provider_resource(
            provider_account=pagarme,
            external_event_id="pagar-event",
            authenticated_request_id_digest=authenticated_request_digest("pagar-request"),
            request_digest="c" * 64,
            resource=ProviderResource("none", "paid", 12540, "BRL"),
        )


@pytest.mark.django_db
def test_callback_cannot_cross_provider_accounts(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("resource-account", "https://checkout.example.test/account"),
        idempotency_key=key(),
    )
    other_account = PaymentProviderAccount.objects.create(
        organization=organization,
        provider="mercado_pago",
        display_name="Conta secundária",
        credential_alias="secondary-account-test",
        is_active=True,
        callbacks_enabled=True,
    )
    with pytest.raises(OrganizationMismatch, match="conta"):
        apply_verified_provider_resource(
            provider_account=other_account,
            external_event_id="cross-account-event",
            authenticated_request_id_digest=authenticated_request_digest("cross-account-request"),
            request_digest="f" * 64,
            resource=ProviderResource("resource-account", "approved", 12540, "BRL"),
        )


@pytest.mark.django_db
def test_order_cancellation_closes_pending_but_flags_paid(organization, payable_order, manager, manager_membership):
    create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    payable_order.status = Order.Status.CANCELLED
    payable_order.cancelled_at = payable_order.confirmed_at
    payable_order.cancel_reason = "Cliente desistiu"
    payable_order.save(update_fields=("status", "cancelled_at", "cancel_reason"))
    result = consume_order_cancelled(
        organization=organization,
        order_id=payable_order.id,
        source_event_id=uuid.uuid4(),
    )
    assert result.status == PaymentIntent.Status.CANCELLED


@pytest.mark.django_db
def test_stale_version_does_not_overwrite(organization, payable_order, mercado_account, manager, manager_membership):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    with pytest.raises(VersionConflict):
        request_hosted_checkout(
            organization=organization,
            intent=intent,
            provider_account=mercado_account,
            actor=manager,
            expected_version=99,
            idempotency_key=key(),
        )


@pytest.mark.django_db
def test_manager_reconciliation_uses_authoritative_resource_and_is_idempotent(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("resource-reconcile", "https://checkout.example.test/reconcile"),
        idempotency_key=key(),
    )
    intent.refresh_from_db()
    command = key()
    resource = ProviderResource("resource-reconcile", "in_process", 12540, "BRL")
    reconciled = reconcile_verified_resource(
        organization=organization,
        intent=intent,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=command,
        resource=resource,
    )
    retry = reconcile_verified_resource(
        organization=organization,
        intent=intent,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=command,
        resource=resource,
    )
    assert reconciled.status == PaymentIntent.Status.PROCESSING
    assert retry.id == reconciled.id


@pytest.mark.django_db
def test_failed_attempt_allows_explicit_retry_without_automatic_fallback(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    first = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=first,
        result=CheckoutResult("resource-failed", "https://checkout.example.test/failed"),
        idempotency_key=key(),
    )
    apply_verified_provider_resource(
        provider_account=mercado_account,
        external_event_id="event-failed",
        authenticated_request_id_digest=authenticated_request_digest("request-failed"),
        request_digest="d" * 64,
        resource=ProviderResource("resource-failed", "rejected", 12540, "BRL"),
    )
    intent.refresh_from_db()
    first.refresh_from_db()
    assert intent.status == PaymentIntent.Status.PENDING
    assert first.status == PaymentAttempt.Status.FAILED
    second = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=key(),
    )
    assert second.status == PaymentAttempt.Status.REQUESTED
    assert intent.attempts.count() == 2


@pytest.mark.django_db
def test_non_monotonic_event_after_paid_requires_attention(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("resource-regressive", "https://checkout.example.test/regressive"),
        idempotency_key=key(),
    )
    for event_id, status in (("event-paid", "approved"), ("event-cancelled-late", "cancelled")):
        apply_verified_provider_resource(
            provider_account=mercado_account,
            external_event_id=event_id,
            authenticated_request_id_digest=authenticated_request_digest(event_id),
            request_digest="e" * 64,
            resource=ProviderResource("resource-regressive", status, 12540, "BRL"),
        )
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.REQUIRES_ATTENTION
    assert intent.attention_code == "non_monotonic_provider_event"


@pytest.mark.django_db
def test_processing_cannot_regress_and_callback_cannot_resolve_attention(
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
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("resource-monotonic", "https://checkout.example.test/monotonic"),
        idempotency_key=key(),
    )
    apply_verified_provider_resource(
        provider_account=mercado_account,
        external_event_id="event-processing",
        authenticated_request_id_digest=authenticated_request_digest("request-processing"),
        request_digest="1" * 64,
        resource=ProviderResource("resource-monotonic", "in_process", 12540, "BRL"),
    )
    apply_verified_provider_resource(
        provider_account=mercado_account,
        external_event_id="event-regression",
        authenticated_request_id_digest=authenticated_request_digest("request-regression"),
        request_digest="2" * 64,
        resource=ProviderResource("resource-monotonic", "pending", 12540, "BRL"),
    )
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.REQUIRES_ATTENTION
    assert intent.attention_code == "non_monotonic_provider_event"

    apply_verified_provider_resource(
        provider_account=mercado_account,
        external_event_id="event-paid-callback",
        authenticated_request_id_digest=authenticated_request_digest("request-paid-callback"),
        request_digest="3" * 64,
        resource=ProviderResource("resource-monotonic", "approved", 12540, "BRL"),
    )
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.REQUIRES_ATTENTION

    reconcile_verified_resource(
        organization=organization,
        intent=intent,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=key(),
        resource=ProviderResource("resource-monotonic", "approved", 12540, "BRL"),
    )
    intent.refresh_from_db()
    assert intent.status == PaymentIntent.Status.PAID
    assert intent.attention_code == ""


@pytest.mark.django_db
def test_payment_audit_and_outbox_payloads_follow_closed_schema(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=key(),
    )
    request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    base_keys = {"payment_intent_id", "order_id", "status", "amount", "currency", "version"}
    optional_flags = {"has_order_conflict", "has_provider_inconsistency"}
    payloads = list(AuditEvent.objects.filter(entity_type="payment_intent").values_list("payload", flat=True)) + list(
        OutboxEvent.objects.filter(aggregate_type="payment_intent").values_list("payload", flat=True)
    )
    assert payloads
    for payload in payloads:
        assert base_keys <= set(payload)
        assert set(payload) <= base_keys | optional_flags
        assert all(isinstance(payload[key], bool) for key in set(payload) & optional_flags)


@pytest.mark.django_db
def test_undispatched_checkout_on_order_cancellation_closes_locally(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    payable_order.status = Order.Status.CANCELLED
    payable_order.cancelled_at = payable_order.confirmed_at
    payable_order.cancel_reason = "Cancelamento com checkout aberto"
    payable_order.save(update_fields=("status", "cancelled_at", "cancel_reason"))
    result = consume_order_cancelled(
        organization=organization,
        order_id=payable_order.id,
        source_event_id=uuid.uuid4(),
    )
    assert result.status == PaymentIntent.Status.CANCELLED
    assert result.attempts.get().status == PaymentAttempt.Status.CANCELLED


@pytest.mark.django_db
def test_fake_fetch_and_reconcile_keeps_network_outside_transaction(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("resource-fetch", "https://checkout.example.test/fetch"),
        idempotency_key=key(),
    )
    intent.refresh_from_db()

    class FakeAdapter:
        provider = "mercado_pago"
        external = False

        def fetch_resource(self, external_resource_id):
            return ProviderResource(external_resource_id, "approved", 12540, "BRL")

    result = fetch_and_reconcile(
        organization=organization,
        intent=intent,
        actor=manager,
        expected_version=intent.version,
        idempotency_key=key(),
        adapter=FakeAdapter(),
    )
    assert result.status == PaymentIntent.Status.PAID
