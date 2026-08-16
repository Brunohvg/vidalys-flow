from dataclasses import dataclass

from apps.messaging.exceptions import InvalidMessage


@dataclass(frozen=True)
class TransactionalTemplateSpec:
    semantic_key: str
    channel: str
    locale: str
    purpose: str
    body_text: str
    body_html: str
    parameter_schema: tuple[str, ...]


_SPECS = (
    TransactionalTemplateSpec(
        semantic_key="order_confirmation",
        channel="whatsapp",
        locale="pt-BR",
        purpose="order_confirmation",
        body_text="Olá {customer_name}, seu pedido {order_number} foi confirmado.",
        body_html="",
        parameter_schema=("customer_name", "order_number"),
    ),
    TransactionalTemplateSpec(
        semantic_key="email_order_confirmation",
        channel="email",
        locale="pt-BR",
        purpose="order_confirmation",
        body_text="Olá {customer_name}, pedido {order_number}.",
        body_html="",
        parameter_schema=("customer_name", "order_number"),
    ),
    TransactionalTemplateSpec(
        semantic_key="fulfillment_ready",
        channel="whatsapp",
        locale="pt-BR",
        purpose="fulfillment_progress",
        body_text="Olá {customer_name}, {order_number}: {fulfillment_status}.",
        body_html="",
        parameter_schema=("customer_name", "order_number", "fulfillment_status"),
    ),
    TransactionalTemplateSpec(
        semantic_key="fulfillment_dispatched",
        channel="whatsapp",
        locale="pt-BR",
        purpose="fulfillment_progress",
        body_text="Olá {customer_name}, {order_number}: {fulfillment_status}.",
        body_html="",
        parameter_schema=("customer_name", "order_number", "fulfillment_status"),
    ),
    TransactionalTemplateSpec(
        semantic_key="fulfillment_completed",
        channel="whatsapp",
        locale="pt-BR",
        purpose="fulfillment_progress",
        body_text="Olá {customer_name}, {order_number}: {fulfillment_status}.",
        body_html="",
        parameter_schema=("customer_name", "order_number", "fulfillment_status"),
    ),
    TransactionalTemplateSpec(
        semantic_key="fulfillment_tracking",
        channel="whatsapp",
        locale="pt-BR",
        purpose="fulfillment_progress",
        body_text=(
            "Olá {customer_name}, o pedido {order_number} foi enviado. "
            "Rastreio: {tracking_code} {tracking_url}"
        ),
        body_html="",
        parameter_schema=("customer_name", "order_number", "tracking_code", "tracking_url"),
    ),
    TransactionalTemplateSpec(
        semantic_key="checkout_link",
        channel="whatsapp",
        locale="pt-BR",
        purpose="checkout_link",
        body_text="Olá {customer_name}, pague seu pedido {order_number} em {checkout_link}.",
        body_html="",
        parameter_schema=("customer_name", "order_number", "checkout_link"),
    ),
    TransactionalTemplateSpec(
        semantic_key="pix_instruction",
        channel="whatsapp",
        locale="pt-BR",
        purpose="pix_instruction",
        body_text=(
            "Olá {customer_name}, para pagar o pedido {order_number} via PIX use "
            "{pix_key_type}: {pix_key}. Beneficiário: {pix_beneficiary}. Banco: {pix_bank}."
        ),
        body_html="",
        parameter_schema=(
            "customer_name",
            "order_number",
            "pix_key_type",
            "pix_key",
            "pix_beneficiary",
            "pix_bank",
        ),
    ),
    TransactionalTemplateSpec(
        semantic_key="payment_paid",
        channel="whatsapp",
        locale="pt-BR",
        purpose="payment_confirmation",
        body_text="Olá {customer_name}, {order_number}: {amount} {currency}.",
        body_html="",
        parameter_schema=("customer_name", "order_number", "amount", "currency"),
    ),
)

TRANSACTIONAL_TEMPLATE_CATALOG = {
    (spec.semantic_key, spec.channel, spec.locale): spec for spec in _SPECS
}


def validate_transactional_template(
    *,
    semantic_key,
    channel,
    locale,
    body_text,
    body_html,
    parameter_schema,
    purpose=None,
):
    spec = TRANSACTIONAL_TEMPLATE_CATALOG.get((semantic_key, channel, locale))
    if spec is None:
        raise InvalidMessage("Template não pertence ao catálogo transacional aprovado.")
    if purpose is not None and purpose != spec.purpose:
        raise InvalidMessage("Template não é aprovado para esta finalidade transacional.")
    if body_text != spec.body_text or (body_html or "") != spec.body_html:
        raise InvalidMessage("Conteúdo diverge do template transacional aprovado.")
    if tuple(parameter_schema or ()) != spec.parameter_schema:
        raise InvalidMessage("Schema diverge do template transacional aprovado.")
    return spec
