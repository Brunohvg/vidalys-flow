def normalize_sku(value):
    return (value or "").strip().upper()


def normalize_barcode(value):
    return "".join(character for character in (value or "").strip() if not character.isspace()).upper()


def normalize_identifier(kind, value):
    normalized = (value or "").strip()
    if kind in {"sku", "internal_code", "supplier_code"}:
        return normalized.upper()
    if kind in {"ean", "gtin"}:
        return "".join(character for character in normalized if character.isdigit())
    return normalized
