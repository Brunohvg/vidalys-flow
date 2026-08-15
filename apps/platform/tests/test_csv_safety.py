import pytest

from apps.platform.csv_safety import spreadsheet_safe_cell


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1:A2)", "-2+3", "@cmd", "\tformula", "\rformula"])
def test_spreadsheet_safe_cell_neutralizes_formula_prefixes(value):
    assert spreadsheet_safe_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["Cliente", "12345", "", None])
def test_spreadsheet_safe_cell_preserves_safe_values(value):
    expected = "" if value is None else str(value)
    assert spreadsheet_safe_cell(value) == expected
