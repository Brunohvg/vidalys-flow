from types import SimpleNamespace

import pytest

from apps.messaging import contextual
from apps.messaging.exceptions import InvalidMessage, ProviderEffectsDisabled
from apps.messaging.models import Message


def _attempt():
    return SimpleNamespace(id="attempt-1", dispatch_lease_token="lease-1")


def _message(*, status=Message.Status.QUEUED, provider="whatsapp_cloud"):
    return SimpleNamespace(
        status=status,
        channel=SimpleNamespace(connection=SimpleNamespace(provider=provider)),
    )


def _adapter(*, provider="whatsapp_cloud", accepted=True, external=False, error=None):
    def send_text(request):
        if error is not None:
            raise error
        return SimpleNamespace(accepted=accepted, provider_message_id="provider-1")

    return SimpleNamespace(
        provider=provider,
        external=external,
        send_text=send_text,
    )


def _patch_claim(monkeypatch, *, message=None, attempt=None):
    message = message or _message()
    attempt = attempt or _attempt()
    monkeypatch.setattr(contextual.services, "claim_dispatch", lambda **kwargs: (message, attempt))
    monkeypatch.setattr(contextual, "assert_capability", lambda *args, **kwargs: None)
    return message, attempt


def _patch_prepare(monkeypatch, *, message, attempt):
    request = SimpleNamespace(body="PIX")
    monkeypatch.setattr(
        contextual,
        "prepare_pix_send_request",
        lambda **kwargs: (message, attempt, request),
    )
    return request


def test_dispatch_returns_uncertain_message_without_provider_call(monkeypatch):
    message = _message(status=Message.Status.UNCERTAIN)
    _, attempt = _patch_claim(monkeypatch, message=message)
    adapter = _adapter(error=AssertionError("provider não deveria ser chamado"))

    result = contextual.dispatch_pix_message(
        attempt=attempt,
        adapter=adapter,
        idempotency_key="idem-1",
    )

    assert result is message


def test_dispatch_releases_lease_when_adapter_provider_mismatches(monkeypatch):
    message, attempt = _patch_claim(monkeypatch, message=_message(provider="whatsapp_cloud"))
    released = {}
    monkeypatch.setattr(contextual.services, "release_dispatch", lambda **kwargs: released.update(kwargs))

    with pytest.raises(InvalidMessage, match="Adapter não corresponde"):
        contextual.dispatch_pix_message(
            attempt=attempt,
            adapter=_adapter(provider="other"),
            idempotency_key="idem-2",
        )

    assert released == {
        "attempt_id": attempt.id,
        "lease_token": attempt.dispatch_lease_token,
        "error_code": "provider_error",
    }


@pytest.mark.parametrize("error", [InvalidMessage("stale"), contextual.OrganizationMismatch("tenant")])
def test_dispatch_marks_failed_when_context_is_stale(monkeypatch, error):
    message, attempt = _patch_claim(monkeypatch)
    monkeypatch.setattr(contextual, "prepare_pix_send_request", lambda **kwargs: (_ for _ in ()).throw(error))
    marked = {}
    monkeypatch.setattr(
        contextual.services,
        "mark_failed",
        lambda **kwargs: marked.update(kwargs) or "failed",
    )

    result = contextual.dispatch_pix_message(
        attempt=attempt,
        adapter=_adapter(),
        idempotency_key="idem-3",
    )

    assert result == "failed"
    assert marked["reason_code"] == "source_not_fresh"
    assert marked["attempt_id"] == attempt.id
    assert marked["lease_token"] == attempt.dispatch_lease_token


def test_dispatch_applies_provider_acceptance(monkeypatch):
    message, attempt = _patch_claim(monkeypatch)
    request = _patch_prepare(monkeypatch, message=message, attempt=attempt)
    applied = {}
    monkeypatch.setattr(
        contextual.services,
        "apply_provider_acceptance",
        lambda **kwargs: applied.update(kwargs) or "accepted",
    )

    result = contextual.dispatch_pix_message(
        attempt=attempt,
        adapter=_adapter(accepted=True),
        idempotency_key="idem-4",
    )

    assert result == "accepted"
    assert applied["attempt_id"] == attempt.id
    assert applied["lease_token"] == attempt.dispatch_lease_token
    assert applied["result"].accepted is True
    assert request.body == "PIX"


def test_dispatch_marks_provider_rejection_failed(monkeypatch):
    message, attempt = _patch_claim(monkeypatch)
    _patch_prepare(monkeypatch, message=message, attempt=attempt)
    marked = {}
    monkeypatch.setattr(
        contextual.services,
        "mark_failed",
        lambda **kwargs: marked.update(kwargs) or "failed",
    )

    result = contextual.dispatch_pix_message(
        attempt=attempt,
        adapter=_adapter(accepted=False),
        idempotency_key="idem-5",
    )

    assert result == "failed"
    assert marked["reason_code"] == "provider_rejected"


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError(), OSError(), RuntimeError("provider")])
def test_dispatch_marks_uncertain_for_ambiguous_provider_failure(monkeypatch, error):
    message, attempt = _patch_claim(monkeypatch)
    _patch_prepare(monkeypatch, message=message, attempt=attempt)
    marked = {}
    monkeypatch.setattr(
        contextual.services,
        "mark_uncertain",
        lambda **kwargs: marked.update(kwargs) or "uncertain",
    )

    result = contextual.dispatch_pix_message(
        attempt=attempt,
        adapter=_adapter(error=error),
        idempotency_key="idem-6",
    )

    assert result == "uncertain"
    assert marked["attempt_id"] == attempt.id
    assert marked["lease_token"] == attempt.dispatch_lease_token


def test_dispatch_releases_lease_when_external_effects_are_disabled(monkeypatch):
    message, attempt = _patch_claim(monkeypatch)
    _patch_prepare(monkeypatch, message=message, attempt=attempt)
    monkeypatch.setattr(
        contextual,
        "require_network_allowed",
        lambda: (_ for _ in ()).throw(ProviderEffectsDisabled("disabled")),
    )
    monkeypatch.setattr(contextual.services, "_dispatch_error_code", lambda exc: "provider_effects_disabled")
    released = {}
    monkeypatch.setattr(contextual.services, "release_dispatch", lambda **kwargs: released.update(kwargs))

    with pytest.raises(ProviderEffectsDisabled):
        contextual.dispatch_pix_message(
            attempt=attempt,
            adapter=_adapter(external=True),
            idempotency_key="idem-7",
        )

    assert released == {
        "attempt_id": attempt.id,
        "lease_token": attempt.dispatch_lease_token,
        "error_code": "provider_effects_disabled",
    }
