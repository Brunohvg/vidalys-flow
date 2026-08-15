import io
import zipfile

import pytest

from apps.platform.xlsx import XlsxError, build_xlsx, parse_xlsx


def test_xlsx_round_trip_preserves_tabular_text():
    payload = build_xlsx(
        headers=("name", "sku"),
        rows=(("Laço & fita", "=literal"), ("Produto 2", "ABC-2")),
    )

    headers, rows = parse_xlsx(payload, max_rows=10)

    assert headers == ("name", "sku")
    assert rows == [
        {"name": "Laço & fita", "sku": "=literal"},
        {"name": "Produto 2", "sku": "ABC-2"},
    ]


def test_xlsx_rejects_formula_cells():
    payload = build_xlsx(headers=("name",), rows=(("safe",),))
    source = io.BytesIO(payload)
    output = io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as changed:
        for info in original.infolist():
            content = original.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                text = content.decode()
                text = text.replace(
                    '<c r="A2" t="inlineStr"><is><t xml:space="preserve">safe</t></is></c>',
                    '<c r="A2"><f>1+1</f><v>2</v></c>',
                )
                content = text.encode()
            changed.writestr(info, content)

    with pytest.raises(XlsxError, match="Fórmulas"):
        parse_xlsx(output.getvalue(), max_rows=10)


def test_xlsx_enforces_row_limit():
    payload = build_xlsx(headers=("name",), rows=(("a",), ("b",)))

    with pytest.raises(XlsxError, match="limite de 1 linhas"):
        parse_xlsx(payload, max_rows=1)
