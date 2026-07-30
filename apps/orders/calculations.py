from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")


def money(value):
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def quantity(value):
    return Decimal(value).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineAmounts:
    quantity: Decimal
    unit_price: Decimal
    gross_total: Decimal
    discount_amount: Decimal
    surcharge_amount: Decimal
    total: Decimal


def calculate_line(*, item_quantity, unit_price, discount_amount=0, surcharge_amount=0):
    normalized_quantity = quantity(item_quantity)
    normalized_price = money(unit_price)
    normalized_discount = money(discount_amount)
    normalized_surcharge = money(surcharge_amount)
    if normalized_quantity <= 0:
        raise ValueError("Quantidade deve ser maior que zero.")
    if min(normalized_price, normalized_discount, normalized_surcharge) < 0:
        raise ValueError("Valores monetários não podem ser negativos.")
    gross = money(normalized_quantity * normalized_price)
    if normalized_discount > gross:
        raise ValueError("Desconto não pode superar o valor bruto do item.")
    return LineAmounts(
        quantity=normalized_quantity,
        unit_price=normalized_price,
        gross_total=gross,
        discount_amount=normalized_discount,
        surcharge_amount=normalized_surcharge,
        total=money(gross - normalized_discount + normalized_surcharge),
    )


def calculate_order(items):
    subtotal = money(sum((item.gross_total for item in items), Decimal("0")))
    discount_total = money(sum((item.discount_amount for item in items), Decimal("0")))
    surcharge_total = money(sum((item.surcharge_amount for item in items), Decimal("0")))
    return {
        "subtotal": subtotal,
        "discount_total": discount_total,
        "surcharge_total": surcharge_total,
        "total": money(subtotal - discount_total + surcharge_total),
    }
