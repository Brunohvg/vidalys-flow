import html
import re

from apps.messaging.exceptions import InvalidMessage

ALLOWED_PARAMETER_KEYS = frozenset(
    {
        "customer_name",
        "order_number",
        "fulfillment_status",
        "checkout_link",
        "amount",
        "currency",
    }
)

PLACEHOLDER_PATTERN = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def validate_parameter_schema(schema):
    if not isinstance(schema, list):
        raise InvalidMessage("Schema de parâmetros deve ser uma lista fechada.")
    keys = []
    for entry in schema:
        if not isinstance(entry, str) or not entry:
            raise InvalidMessage("Schema de parâmetros contém entrada inválida.")
        if entry not in ALLOWED_PARAMETER_KEYS:
            raise InvalidMessage(f"Parâmetro fora do schema aprovado: {entry}.")
        keys.append(entry)
    if len(keys) != len(set(keys)):
        raise InvalidMessage("Schema de parâmetros não pode repetir chaves.")
    return keys


def placeholders(text):
    return set(PLACEHOLDER_PATTERN.findall(text or ""))


def _escape_value(value):
    text = str(value)
    if any(ch in text for ch in ("\r", "\n", "\x00")):
        raise InvalidMessage("Valor de parâmetro contém caracteres de controle.")
    return text


def render_message_body(*, template, parameters):
    schema = validate_parameter_schema(template.parameter_schema)
    provided = set(parameters or {})
    expected_text = placeholders(template.body_text)
    expected_html = placeholders(template.body_html) if template.body_html else set()
    expected = expected_text | expected_html
    if provided != expected:
        raise InvalidMessage("Parâmetros fornecidos não correspondem ao schema fechado do template.")
    if not expected.issubset(schema):
        raise InvalidMessage("Template referencia parâmetro fora do schema aprovado.")
    values = {key: _escape_value(parameters[key]) for key in provided}

    class SafeDict(dict):
        def __missing__(self, key):
            raise InvalidMessage(f"Parâmetro ausente ao renderizar: {key}.")

    text_body = template.body_text.format_map(SafeDict(values)) if template.body_text else ""
    if template.body_html:
        html_values = {key: html.escape(str(parameters[key])) for key in provided}
        html_body = template.body_html.format_map(SafeDict(html_values))
    else:
        html_body = ""
    return text_body, html_body
