from dataclasses import dataclass
from decimal import Decimal

from apps.payments.exceptions import InvalidPayment, ProviderEffectsDisabled
from apps.payments.models import PaymentProviderAccount


@dataclass(frozen=True)
class CheckoutRequest:
    reference: str
    amount_minor: int
    currency: str
    idempotency_key: str


@dataclass(frozen=True)
class CheckoutResult:
    external_resource_id: str
    hosted_url: str
    expires_at: object = None


@dataclass(frozen=True)
class ProviderResource:
    external_resource_id: str
    status: str
    amount_minor: int
    currency: str


def amount_to_minor_units(amount):
    value = Decimal(amount)
    minor = value * 100
    if minor != minor.to_integral_value():
        raise InvalidPayment("Valor monetário não pode ser convertido exatamente em centavos.")
    return int(minor)


def build_checkout_request(*, intent, idempotency_key):
    return CheckoutRequest(
        reference=str(intent.id),
        amount_minor=amount_to_minor_units(intent.amount),
        currency=intent.currency,
        idempotency_key=idempotency_key,
    )


def map_provider_status(*, provider, status):
    mappings = {
        PaymentProviderAccount.Provider.MERCADO_PAGO: {
            "pending": "awaiting_payment",
            "in_process": "processing",
            "approved": "paid",
            "cancelled": "cancelled",
            "rejected": "failed",
            "refunded": "requires_attention",
            "charged_back": "requires_attention",
        },
        PaymentProviderAccount.Provider.PAGARME: {
            "pending": "awaiting_payment",
            "processing": "processing",
            "paid": "paid",
            "canceled": "cancelled",
            "failed": "failed",
            "expired": "expired",
        },
    }
    try:
        return mappings[provider][status]
    except KeyError as exc:
        raise InvalidPayment("Estado de provider desconhecido.") from exc


class DisabledProviderAdapter:
    external = True

    def create_checkout(self, request):
        raise ProviderEffectsDisabled("Efeitos externos de Payments estão desabilitados.")

    def fetch_resource(self, external_resource_id):
        raise ProviderEffectsDisabled("Efeitos externos de Payments estão desabilitados.")

    def cancel_checkout(self, external_resource_id, *, idempotency_key):
        raise ProviderEffectsDisabled("Efeitos externos de Payments estão desabilitados.")


class MercadoPagoCheckoutProAdapter(DisabledProviderAdapter):
    provider = PaymentProviderAccount.Provider.MERCADO_PAGO

    @staticmethod
    def contract_payload(request):
        return {
            "external_reference": request.reference,
            "items": [
                {
                    "id": request.reference,
                    "title": "Pedido Vidalys Flow",
                    "quantity": 1,
                    "currency_id": request.currency,
                    "unit_price": (Decimal(request.amount_minor) / 100).quantize(Decimal("0.01")),
                }
            ],
        }


class PagarmePaymentLinkAdapter(DisabledProviderAdapter):
    provider = PaymentProviderAccount.Provider.PAGARME

    @staticmethod
    def contract_payload(request):
        return {
            "type": "order",
            "name": f"Pedido {request.reference}",
            "order_code": request.reference,
            "max_paid_sessions": 1,
            "payment_settings": {
                "accepted_payment_methods": ["credit_card", "pix", "boleto"],
                "credit_card_settings": {"operation_type": "auth_and_capture"},
                "pix_settings": {},
                "boleto_settings": {},
            },
            "cart_settings": {
                "items": [
                    {
                        "name": "Pedido Vidalys Flow",
                        "amount": request.amount_minor,
                        "default_quantity": 1,
                    }
                ]
            },
        }
