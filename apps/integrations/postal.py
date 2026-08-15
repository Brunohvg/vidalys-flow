from dataclasses import dataclass
from typing import Protocol


class PostalAddressError(ValueError):
    pass


class PostalAddressUnavailable(PostalAddressError):
    pass


@dataclass(frozen=True, slots=True)
class PostalAddress:
    postal_code: str
    street: str = ""
    district: str = ""
    city: str = ""
    state: str = ""
    country: str = "BR"


class PostalAddressAdapter(Protocol):
    def lookup(self, *, postal_code: str) -> PostalAddress:
        """Resolve one normalized postal code without mutating application state."""


def normalize_postal_code(value: str) -> str:
    normalized = "".join(character for character in (value or "") if character.isdigit())
    if len(normalized) != 8:
        raise PostalAddressError("CEP deve conter 8 dígitos.")
    return normalized


def lookup_postal_address(*, postal_code: str, adapter: PostalAddressAdapter | None = None) -> PostalAddress:
    normalized = normalize_postal_code(postal_code)
    if adapter is None:
        raise PostalAddressUnavailable(
            "Consulta automática de CEP não está habilitada. Preencha o endereço manualmente."
        )

    result = adapter.lookup(postal_code=normalized)
    if normalize_postal_code(result.postal_code) != normalized:
        raise PostalAddressError("O provider retornou um CEP diferente do solicitado.")
    return result
