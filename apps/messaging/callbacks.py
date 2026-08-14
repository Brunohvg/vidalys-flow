import hashlib
import hmac
import json
import re

from django.core.cache import cache

from apps.messaging.exceptions import CallbackRejected, ProviderEffectsDisabled
from apps.messaging.models import MessageWebhookReceipt, MessagingProviderConnection
from apps.messaging.services import apply_delivery_evidence

MAX_CALLBACK_BYTES = 64 * 1024
CALLBACK_RATE_LIMIT_PER_MINUTE = 120
CALLBACK_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def _validated_callback_identifier(value, *, label, max_length):
    if isinstance(value, bool) or not isinstance(value, str):
        raise CallbackRejected(f"{label} de callback inválido.")
    if not value or len(value) > max_length or CALLBACK_IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise CallbackRejected(f"{label} de callback inválido.")
    return value


def request_digest(raw_body):
    if len(raw_body) > MAX_CALLBACK_BYTES:
        raise CallbackRejected("Callback excede o limite permitido.")
    return hashlib.sha256(raw_body).hexdigest()


def enforce_callback_rate_limit(*, channel_id, remote_address, limit=CALLBACK_RATE_LIMIT_PER_MINUTE):
    subject = hashlib.sha256(f"{channel_id}:{remote_address}".encode()).hexdigest()
    cache_key = f"messaging:callback-rate:{subject}"
    try:
        count = 1 if cache.add(cache_key, 1, timeout=60) else cache.incr(cache_key)
    except Exception as exc:  # noqa: BLE001 - unavailable limiter must fail closed
        raise ProviderEffectsDisabled("Limitador de callbacks indisponível.") from exc
    if count > limit:
        raise CallbackRejected("Limite de callbacks excedido.")


def verify_secret_header(*, signature_header, secret):
    if not signature_header or not secret:
        raise CallbackRejected("Segredo de callback ausente.")
    if not hmac.compare_digest(signature_header, secret):
        raise CallbackRejected("Segredo de callback inválido.")


def resolve_webhook_secret(*, connection):
    raise ProviderEffectsDisabled("Canal de secrets de Messaging não está ativado.")


def process_delivery_callback(
    *,
    channel,
    raw_body,
    request_id,
    signature_header,
    secret_resolver=None,
):
    connection = channel.connection
    if not connection.is_active or not connection.callbacks_enabled:
        raise CallbackRejected("Callback desabilitado.")
    if connection.provider != MessagingProviderConnection.Provider.EVOLUTION:
        raise ProviderEffectsDisabled("Callback deste provider ainda não possui autenticidade aprovada.")
    digest = request_digest(raw_body)
    try:
        payload = json.loads(raw_body)
        external_message_id = _validated_callback_identifier(
            payload["message_id"],
            label="Message ID",
            max_length=200,
        )
        provider_status = _validated_callback_identifier(payload["status"], label="Status", max_length=60)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CallbackRejected("Callback malformado.") from exc
    request_id = _validated_callback_identifier(request_id, label="Request ID", max_length=128)
    resolver = secret_resolver or resolve_webhook_secret
    secret = resolver(connection=connection)
    verify_secret_header(
        signature_header=signature_header,
        secret=secret,
    )
    authenticated_request_id_digest = hashlib.sha256(request_id.encode()).hexdigest()
    external_event_id = hashlib.sha256(f"{connection.id}:{external_message_id}:{request_id}".encode()).hexdigest()
    existing = MessageWebhookReceipt.objects.filter(
        channel=channel,
        external_message_id=external_message_id,
        authenticated_request_id_digest=authenticated_request_id_digest,
    ).first()
    if existing:
        return existing
    return apply_delivery_evidence(
        channel=channel,
        connection=connection,
        external_event_id=external_event_id,
        external_message_id=external_message_id,
        provider_status=provider_status,
        authenticated_request_id_digest=authenticated_request_id_digest,
        request_digest=digest,
    )
