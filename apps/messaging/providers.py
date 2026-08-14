import hashlib
import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

from apps.messaging.exceptions import ProviderEffectsDisabled, UnsafeProviderUrl
from apps.messaging.models import MessagingProviderConnection
from apps.platform.guardrails import external_effects_blocked

CAPABILITIES = {
    "linked_device_pairing",
    "official_templates",
    "send_text",
    "delivery_receipts",
    "message_status_query",
    "multiple_channels",
    "webhook_signature",
    "provider_idempotency",
}

PROVIDER_CAPABILITIES = {
    MessagingProviderConnection.Provider.EVOLUTION: {
        "linked_device_pairing",
        "send_text",
        "delivery_receipts",
        "message_status_query",
        "multiple_channels",
    },
    MessagingProviderConnection.Provider.WHATSAPP_CLOUD: {
        "official_templates",
        "send_text",
        "delivery_receipts",
        "multiple_channels",
        "webhook_signature",
    },
    MessagingProviderConnection.Provider.SES: {
        "send_text",
        "delivery_receipts",
        "multiple_channels",
        "webhook_signature",
    },
}

PROVIDER_CHANNEL_KINDS = {
    MessagingProviderConnection.Provider.EVOLUTION: "whatsapp",
    MessagingProviderConnection.Provider.WHATSAPP_CLOUD: "whatsapp",
    MessagingProviderConnection.Provider.SES: "email",
}

PROVIDER_MODES = {
    MessagingProviderConnection.Provider.EVOLUTION: MessagingProviderConnection.Mode.LINKED_DEVICE,
    MessagingProviderConnection.Provider.WHATSAPP_CLOUD: MessagingProviderConnection.Mode.OFFICIAL,
    MessagingProviderConnection.Provider.SES: MessagingProviderConnection.Mode.EMAIL,
}

PRIVATE_IP_ERROR = "Host resolve para endereço privado ou reservado (SSRF bloqueado)."
ALLOWLIST_ERROR = "Host do provider não está na allowlist aprovada."


def provider_capabilities(provider):
    try:
        return PROVIDER_CAPABILITIES[provider]
    except KeyError as exc:
        raise ProviderEffectsDisabled("Provider desconhecido.") from exc


def provider_channel_kind(provider):
    try:
        return PROVIDER_CHANNEL_KINDS[provider]
    except KeyError as exc:
        raise ProviderEffectsDisabled("Provider desconhecido.") from exc


def validate_provider_mode(*, provider, mode):
    try:
        expected = PROVIDER_MODES[provider]
    except KeyError as exc:
        raise ProviderEffectsDisabled("Provider desconhecido.") from exc
    if mode != expected:
        raise ProviderEffectsDisabled("Modo incompatível com o provider.")


def has_capability(provider, capability):
    return capability in provider_capabilities(provider)


def assert_capability(provider, capability):
    if not has_capability(provider, capability):
        raise ProviderEffectsDisabled(f"Provider não declara a capability '{capability}'.")


def _is_private_address(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def validate_evolution_url(url, *, allowlist=()):
    """Validate an Evolution base URL without resolving DNS.

    Enforces HTTPS, absence of embedded credentials, an explicit hostname,
    no private/loopback IP literal, and membership in the exact allowlist.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeProviderUrl("Evolution exige HTTPS.")
    if parsed.username or parsed.password:
        raise UnsafeProviderUrl("URL não pode conter credenciais embutidas.")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise UnsafeProviderUrl("URL sem hostname.")
    if parsed.port not in (None, 443):
        raise UnsafeProviderUrl("Somente a porta HTTPS padrão é permitida.")
    try:
        ipaddress.ip_address(hostname)
        raise UnsafeProviderUrl(PRIVATE_IP_ERROR)
    except ValueError:
        pass
    normalized_allowlist = [entry.lower().rstrip(".") for entry in allowlist]
    if hostname not in normalized_allowlist and not any(
        hostname.endswith("." + entry) for entry in normalized_allowlist if entry
    ):
        raise UnsafeProviderUrl(ALLOWLIST_ERROR)
    return f"https://{hostname}"


def validate_resolved_addresses(hostname, addresses):
    """Defend against DNS rebinding/SSRF once an address has been resolved."""
    if not addresses:
        raise UnsafeProviderUrl("Host do provider não resolve para nenhum endereço.")
    for address in addresses:
        if _is_private_address(str(address)):
            raise UnsafeProviderUrl(PRIVATE_IP_ERROR)
    return True


def evolution_instance_name(*, organization_id, channel_id):
    digest = hashlib.sha256(f"{organization_id}:{channel_id}".encode()).hexdigest()
    return f"vf-{digest[:24]}"


@dataclass(frozen=True)
class SendRequest:
    destination: str
    body: str
    body_html: str
    template_reference: str
    provider_correlation_tag: str
    channel_kind: str
    provider: str
    locale: str = "pt-BR"
    template_parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class SendResult:
    external_message_id: str
    accepted: bool


class DisabledProviderAdapter:
    external = True

    def send_text(self, request):
        raise ProviderEffectsDisabled("Efeitos externos de Messaging estão desabilitados.")

    def fetch_status(self, external_message_id):
        raise ProviderEffectsDisabled("Consulta externa de Messaging não está ativada.")


class EvolutionAdapter(DisabledProviderAdapter):
    provider = MessagingProviderConnection.Provider.EVOLUTION

    @staticmethod
    def contract_payload(request):
        return {
            "number": "".join(character for character in request.destination if character.isdigit()),
            "textMessage": {"text": request.body},
        }


class WhatsAppCloudAdapter(DisabledProviderAdapter):
    provider = MessagingProviderConnection.Provider.WHATSAPP_CLOUD

    @staticmethod
    def contract_payload(request):
        return {
            "messaging_product": "whatsapp",
            "to": "".join(character for character in request.destination if character.isdigit()),
            "type": "template",
            "template": {
                "name": request.template_reference,
                "language": {"code": request.locale.replace("-", "_")},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": value} for value in request.template_parameters],
                    }
                ],
            },
        }


class SesAdapter(DisabledProviderAdapter):
    provider = MessagingProviderConnection.Provider.SES

    @staticmethod
    def contract_payload(request):
        message = {
            "Subject": {"Data": "Vidalys Flow"},
            "Body": {"Text": {"Data": request.body}},
        }
        if request.body_html:
            message["Body"]["Html"] = {"Data": request.body_html}
        return {
            "Destination": {"ToAddresses": [request.destination]},
            "Message": message,
            "ConfigurationSetName": "vidalys-flow-delivery",
        }


ADAPTERS = {
    MessagingProviderConnection.Provider.EVOLUTION: EvolutionAdapter,
    MessagingProviderConnection.Provider.WHATSAPP_CLOUD: WhatsAppCloudAdapter,
    MessagingProviderConnection.Provider.SES: SesAdapter,
}


def adapter_for(provider):
    try:
        return ADAPTERS[provider]()
    except KeyError as exc:
        raise ProviderEffectsDisabled("Provider desconhecido.") from exc


def require_network_allowed():
    if external_effects_blocked():
        raise ProviderEffectsDisabled("Efeitos externos de Messaging estão desabilitados.")


DELIVERY_STATUS_MAP = {
    MessagingProviderConnection.Provider.EVOLUTION: {
        "sent": "sent",
        "delivered": "delivered",
        "read": "delivered",
        "failed": "failed",
    },
    MessagingProviderConnection.Provider.WHATSAPP_CLOUD: {
        "sent": "sent",
        "delivered": "delivered",
        "read": "delivered",
        "failed": "failed",
    },
    MessagingProviderConnection.Provider.SES: {
        "delivered": "delivered",
        "bounce": "failed",
        "complaint": "failed",
        "reject": "failed",
    },
}

HARD_FEEDBACK_STATUSES = {"bounce", "complaint", "reject"}


def map_delivery_status(*, provider, status):
    try:
        return DELIVERY_STATUS_MAP[provider][status]
    except KeyError as exc:
        raise UnsafeProviderUrl("Estado de entrega do provider desconhecido.") from exc
