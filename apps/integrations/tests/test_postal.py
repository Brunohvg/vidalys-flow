import pytest

from apps.integrations.postal import (
    PostalAddress,
    PostalAddressError,
    PostalAddressUnavailable,
    lookup_postal_address,
    normalize_postal_code,
)


class FakePostalAdapter:
    def __init__(self, result):
        self.result = result
        self.received = None

    def lookup(self, *, postal_code):
        self.received = postal_code
        return self.result


def test_normalize_postal_code_accepts_formatted_brazilian_cep():
    assert normalize_postal_code("30130-110") == "30130110"


def test_normalize_postal_code_rejects_invalid_length():
    with pytest.raises(PostalAddressError):
        normalize_postal_code("30130")


def test_lookup_is_fail_closed_without_authorized_adapter():
    with pytest.raises(PostalAddressUnavailable, match="não está habilitada"):
        lookup_postal_address(postal_code="30130-110")


def test_lookup_uses_normalized_code_and_returns_provider_neutral_address():
    adapter = FakePostalAdapter(
        PostalAddress(
            postal_code="30130110",
            street="Rua da Bahia",
            city="Belo Horizonte",
            state="MG",
        )
    )

    result = lookup_postal_address(postal_code="30130-110", adapter=adapter)

    assert adapter.received == "30130110"
    assert result.city == "Belo Horizonte"
    assert result.state == "MG"


def test_lookup_rejects_mismatched_provider_response():
    adapter = FakePostalAdapter(PostalAddress(postal_code="01001000"))

    with pytest.raises(PostalAddressError, match="diferente"):
        lookup_postal_address(postal_code="30130-110", adapter=adapter)
