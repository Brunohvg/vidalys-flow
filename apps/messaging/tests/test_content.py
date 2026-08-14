import pytest

from apps.messaging.content import ALLOWED_PARAMETER_KEYS, placeholders, render_message_body, validate_parameter_schema
from apps.messaging.exceptions import InvalidMessage


def test_parameter_schema_accepts_allowlisted_scalars():
    assert validate_parameter_schema(["customer_name", "order_number", "checkout_link"]) == [
        "customer_name",
        "order_number",
        "checkout_link",
    ]


def test_parameter_schema_rejects_outside_allowlist():
    with pytest.raises(InvalidMessage):
        validate_parameter_schema(["customer_name", "credit_card_number"])


def test_parameter_schema_rejects_duplicates():
    with pytest.raises(InvalidMessage):
        validate_parameter_schema(["customer_name", "customer_name"])


def test_parameter_schema_rejects_non_list():
    with pytest.raises(InvalidMessage):
        validate_parameter_schema({"customer_name": "x"})


def test_parameter_schema_rejects_non_string_entry():
    with pytest.raises(InvalidMessage):
        validate_parameter_schema([42])


def test_placeholders_extract_closed_variables():
    assert placeholders("Olá {customer_name}, pedido {order_number}") == {"customer_name", "order_number"}
    assert placeholders("") == set()


def test_render_requires_exact_parameters():
    template = type(
        "T", (), {"body_text": "Olá {customer_name}", "body_html": "", "parameter_schema": ["customer_name"]}
    )()
    assert render_message_body(template=template, parameters={"customer_name": "Ana"}) == ("Olá Ana", "")
    with pytest.raises(InvalidMessage):
        render_message_body(template=template, parameters={"customer_name": "Ana", "extra": "x"})
    with pytest.raises(InvalidMessage):
        render_message_body(template=template, parameters={})


def test_render_rejects_placeholder_outside_schema():
    template = type(
        "T",
        (),
        {"body_text": "Olá {customer_name} {order_number}", "body_html": "", "parameter_schema": ["customer_name"]},
    )()
    with pytest.raises(InvalidMessage):
        render_message_body(template=template, parameters={"customer_name": "Ana", "order_number": "PED-1"})


def test_render_rejects_control_characters():
    template = type(
        "T", (), {"body_text": "Olá {customer_name}", "body_html": "", "parameter_schema": ["customer_name"]}
    )()
    with pytest.raises(InvalidMessage):
        render_message_body(template=template, parameters={"customer_name": "Ana\ninjetada"})


def test_render_escapes_html_body():
    template = type(
        "T",
        (),
        {
            "body_text": "Olá {customer_name}",
            "body_html": "<p>{customer_name}</p>",
            "parameter_schema": ["customer_name"],
        },
    )()
    text, html = render_message_body(template=template, parameters={"customer_name": "<script>alert(1)</script>"})
    assert text == "Olá <script>alert(1)</script>"
    assert html == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"


def test_allowlist_is_closed_and_documented():
    assert {
        "customer_name",
        "order_number",
        "fulfillment_status",
        "checkout_link",
        "amount",
        "currency",
    } == ALLOWED_PARAMETER_KEYS
