import pytest

from apps.customers.normalization import (
    mask_contact,
    mask_document,
    normalize_document,
    normalize_email,
    normalize_phone,
)


def test_normalize_email_lowercases_and_strips():
    assert normalize_email("  Person@Example.COM ") == "person@example.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(11) 99999-1234", "+5511999991234"),
        ("+1 415 555 2671", "+14155552671"),
        ("5511999991234", "+5511999991234"),
    ],
)
def test_normalize_phone_to_e164_style(raw, expected):
    assert normalize_phone(raw) == expected


def test_normalize_valid_cpf_and_cnpj():
    assert normalize_document("529.982.247-25") == "52998224725"
    assert normalize_document("04.252.011/0001-10") == "04252011000110"


def test_invalid_document_does_not_echo_value():
    raw = "111.111.111-11"
    with pytest.raises(ValueError) as error:
        normalize_document(raw)
    assert raw not in str(error.value)


def test_empty_document_and_phone_remain_empty():
    assert normalize_document("") == ""
    assert normalize_phone("") == ""


def test_mask_personal_data():
    assert mask_document("52998224725").endswith("4725")
    assert mask_contact("email", "person@example.com") == "pe***@example.com"
    assert mask_contact("phone", "+5511999991234") == "+55****34"
    assert mask_contact("phone", "") == ""
