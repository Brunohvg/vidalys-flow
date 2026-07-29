import re


def _digits(value):
    return re.sub(r"\D", "", value or "")


def _cpf_is_valid(value):
    numbers = [int(digit) for digit in value[:9]]
    for _ in range(2):
        weight = len(numbers) + 1
        total = sum(number * (weight - index) for index, number in enumerate(numbers))
        remainder = (total * 10) % 11
        numbers.append(0 if remainder == 10 else remainder)
    return "".join(str(number) for number in numbers) == value


def _cnpj_is_valid(value):
    numbers = [int(digit) for digit in value[:12]]
    weights = (
        (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
        (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
    )
    for current_weights in weights:
        total = sum(number * weight for number, weight in zip(numbers, current_weights, strict=True))
        remainder = total % 11
        numbers.append(0 if remainder < 2 else 11 - remainder)
    return "".join(str(number) for number in numbers) == value


def normalize_document(value):
    normalized = _digits(value)
    if not normalized:
        return ""
    if len(set(normalized)) == 1:
        raise ValueError("Documento inválido.")
    if len(normalized) == 11 and _cpf_is_valid(normalized):
        return normalized
    if len(normalized) == 14 and _cnpj_is_valid(normalized):
        return normalized
    raise ValueError("Documento deve ser um CPF ou CNPJ válido.")


def normalize_email(value):
    return (value or "").strip().lower()


def normalize_phone(value):
    raw = (value or "").strip()
    normalized = _digits(raw)
    if not normalized:
        return ""
    if raw.startswith("+"):
        return f"+{normalized}"
    if len(normalized) in {10, 11}:
        return f"+55{normalized}"
    if len(normalized) in {12, 13} and normalized.startswith("55"):
        return f"+{normalized}"
    return f"+{normalized}"


def mask_document(value):
    if not value:
        return ""
    return f"{'*' * max(len(value) - 4, 0)}{value[-4:]}"


def mask_contact(kind, value):
    if not value:
        return ""
    if kind == "email" and "@" in value:
        local, domain = value.split("@", 1)
        return f"{local[:2]}***@{domain}"
    return f"{value[:3]}****{value[-2:]}"
