import hashlib
import hmac
import json
import time

from django.core.cache import cache

from apps.payments.exceptions import CallbackRejected, ProviderEffectsDisabled
from apps.payments.models import PaymentProviderAccount
from apps.payments.services import apply_verified_provider_resource

MAX_CALLBACK_BYTES = 64 * 1024
CALLBACK_RATE_LIMIT_PER_MINUTE = 120


def request_digest(raw_body):
    if len(raw_body) > MAX_CALLBACK_BYTES:
        raise CallbackRejected("Callback excede o limite permitido.")
    return hashlib.sha256(raw_body).hexdigest()


def enforce_callback_rate_limit(*, provider_account_id, remote_address, limit=CALLBACK_RATE_LIMIT_PER_MINUTE):
    subject = hashlib.sha256(f"{provider_account_id}:{remote_address}".encode()).hexdigest()
    cache_key = f"payments:callback-rate:{subject}"
    try:
        count = 1 if cache.add(cache_key, 1, timeout=60) else cache.incr(cache_key)
    except Exception as exc:  # noqa: BLE001 - unavailable limiter must fail closed
        raise ProviderEffectsDisabled("Limitador de callbacks indisponível.") from exc
    if count > limit:
        raise CallbackRejected("Limite de callbacks excedido.")


def verify_mercado_pago_signature(*, data_id, request_id, signature_header, signing_value, now=None):
    parts = {}
    for component in signature_header.split(","):
        key, separator, value = component.strip().partition("=")
        if separator:
            parts[key] = value
    timestamp = parts.get("ts", "")
    received = parts.get("v1", "")
    if not timestamp or not received or not request_id or not data_id or not signing_value:
        raise CallbackRejected("Assinatura de callback ausente ou incompleta.")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise CallbackRejected("Timestamp de callback inválido.") from exc
    if abs(int(now if now is not None else time.time()) - timestamp_value) > 300:
        raise CallbackRejected("Callback fora da janela contra replay.")
    manifest = f"id:{data_id};request-id:{request_id};ts:{timestamp};"
    expected = hmac.new(signing_value.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received, expected):
        raise CallbackRejected("Assinatura de callback inválida.")
    return True


def require_callback_enabled(*, provider_account):
    if not provider_account.is_active or not provider_account.callbacks_enabled:
        raise CallbackRejected("Callback desabilitado.")
    if provider_account.provider != PaymentProviderAccount.Provider.MERCADO_PAGO:
        raise CallbackRejected("Callback deste provider permanece bloqueado.")


def resolve_signing_value(*, provider_account):
    raise ProviderEffectsDisabled("Canal de secrets de Payments não está ativado.")


def fetch_authoritative_resource(*, provider_account, external_resource_id):
    raise ProviderEffectsDisabled("Consulta externa de Payments não está ativada.")


def process_mercado_pago_callback(
    *, provider_account, raw_body, request_id, signature_header, signing_resolver=None, resource_loader=None
):
    require_callback_enabled(provider_account=provider_account)
    digest = request_digest(raw_body)
    try:
        payload = json.loads(raw_body)
        external_event_id = str(payload["id"])
        external_resource_id = str(payload["data"]["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CallbackRejected("Callback malformado.") from exc
    resolver = signing_resolver or resolve_signing_value
    signing_value = resolver(provider_account=provider_account)
    verify_mercado_pago_signature(
        data_id=external_resource_id,
        request_id=request_id,
        signature_header=signature_header,
        signing_value=signing_value,
    )
    loader = resource_loader or fetch_authoritative_resource
    resource = loader(
        provider_account=provider_account,
        external_resource_id=external_resource_id,
    )
    if resource.external_resource_id != external_resource_id:
        raise CallbackRejected("Consulta autoritativa retornou recurso divergente.")
    return apply_verified_provider_resource(
        provider_account=provider_account,
        external_event_id=external_event_id,
        request_digest=digest,
        resource=resource,
    )
