from decimal import Decimal

import pytest

from apps.orders.calculations import calculate_line, calculate_order


def test_rounds_each_line_half_up_before_aggregation():
    first = calculate_line(item_quantity="0.333", unit_price="0.05")
    second = calculate_line(item_quantity="0.333", unit_price="0.05")
    totals = calculate_order([first, second])
    assert first.gross_total == Decimal("0.02")
    assert totals["subtotal"] == Decimal("0.04")
    assert totals["total"] == Decimal("0.04")


def test_line_applies_discount_and_surcharge_after_gross_rounding():
    line = calculate_line(
        item_quantity="2.500",
        unit_price="10.00",
        discount_amount="2.00",
        surcharge_amount="1.25",
    )
    assert line.gross_total == Decimal("25.00")
    assert line.total == Decimal("24.25")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"item_quantity": "0", "unit_price": "1"},
        {"item_quantity": "1", "unit_price": "-1"},
        {"item_quantity": "1", "unit_price": "1", "discount_amount": "1.01"},
        {"item_quantity": "1", "unit_price": "1", "surcharge_amount": "-0.01"},
    ],
)
def test_invalid_line_values_are_refused(kwargs):
    with pytest.raises(ValueError):
        calculate_line(**kwargs)
