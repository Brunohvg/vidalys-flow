import hashlib
import hmac
import time

import pytest
from django.core.cache import cache

from apps.payments.callbacks import (
    MAX_CALLBACK_BYTES,
    enforce_callback_rate_limit,
    process_mercado_pago_callback,
    request_digest,
    require_callback_enabled,
    verify_mercado_pago_signature,
)
from apps.payments.exceptions import CallbackRejected, ProviderEffectsDisabled
from apps.payments.models import PaymentProviderAccount
from apps.payments.providers import CheckoutResult, ProviderResource
from apps.payments.services import activate_hosted_checkout, create_payment_intent, request_hosted_checkout


def key():
    import uuid

    return str(uuid.uuid4())


def test_mercado_pago_signature_and_payload_limit():
    signing_value = "test-only-signing-value"
    manifest = "id:123;request-id:req-1;ts:1700000000;"
    signature = hmac.new(signing_value.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    assert verify_mercado_pago_signature(
        data_id="123",
        request_id="req-1",
        signature_header=f"ts=1700000000,v1={signature}",
        signing_value=signing_value,
        now=1700000000,
    )
    with pytest.raises(CallbackRejected):
        verify_mercado_pago_signature(
            data_id="123",
            request_id="req-1",
            signature_header="ts=1700000000,v1=wrong",
            signing_value=signing_value,
            now=1700000000,
        )
    with pytest.raises(CallbackRejected, match="replay"):
        verify_mercado_pago_signature(
            data_id="123",
            request_id="req-1",
            signature_header=f"ts=1700000000,v1={signature}",
            signing_value=signing_value,
            now=1700001000,
        )
    assert len(request_digest(b"{}")) == 64
    with pytest.raises(CallbackRejected, match="limite"):
        request_digest(b"x" * (MAX_CALLBACK_BYTES + 1))


def test_callback_rate_limit_uses_hashed_subject():
    cache.clear()
    enforce_callback_rate_limit(provider_account_id="account", remote_address="127.0.0.1", limit=1)
    with pytest.raises(CallbackRejected, match="Limite"):
        enforce_callback_rate_limit(provider_account_id="account", remote_address="127.0.0.1", limit=1)


@pytest.mark.django_db
def test_pagarme_callbacks_remain_disabled(organization):
    account = PaymentProviderAccount.objects.create(
        organization=organization,
        provider="pagarme",
        display_name="Pagar.me",
        credential_alias="callback-disabled-test",
        is_active=True,
    )
    with pytest.raises(CallbackRejected, match="desabilitado"):
        require_callback_enabled(provider_account=account)


@pytest.mark.django_db
def test_callback_uses_signature_and_authoritative_resource_without_storing_body(
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
        result=CheckoutResult("resource-callback", "https://checkout.example.test/callback"),
        idempotency_key=key(),
    )
    raw = b'{"id":"event-callback","data":{"id":"resource-callback"},"payer":{"email":"private@example.test"}}'
    signing_value = "callback-test-value"
    timestamp = int(time.time())
    manifest = f"id:resource-callback;request-id:req-callback;ts:{timestamp};"
    signature = hmac.new(signing_value.encode(), manifest.encode(), hashlib.sha256).hexdigest()

    receipt = process_mercado_pago_callback(
        provider_account=mercado_account,
        raw_body=raw,
        request_id="req-callback",
        signature_header=f"ts={timestamp},v1={signature}",
        signing_resolver=lambda **kwargs: signing_value,
        resource_loader=lambda **kwargs: ProviderResource("resource-callback", "approved", 12540, "BRL"),
    )

    intent.refresh_from_db()
    assert intent.status == "paid"
    assert receipt.request_digest == hashlib.sha256(raw).hexdigest()
    assert "private@example.test" not in str(receipt.__dict__)
    evidence = str(list(organization.audit_events.values_list("payload", flat=True))) + str(
        list(organization.outbox_events.values_list("payload", flat=True))
    )
    assert "private@example.test" not in evidence


@pytest.mark.django_db
def test_callback_rejects_malformed_divergent_and_unconfigured_effects(mercado_account):
    with pytest.raises(CallbackRejected, match="malformado"):
        process_mercado_pago_callback(
            provider_account=mercado_account,
            raw_body=b"{}",
            request_id="req",
            signature_header="ts=1,v1=invalid",
            signing_resolver=lambda **kwargs: "unused",
            resource_loader=lambda **kwargs: None,
        )
    raw = b'{"id":"event","data":{"id":"resource"}}'
    with pytest.raises(ProviderEffectsDisabled):
        process_mercado_pago_callback(
            provider_account=mercado_account,
            raw_body=raw,
            request_id="req",
            signature_header="ts=1,v1=invalid",
        )
