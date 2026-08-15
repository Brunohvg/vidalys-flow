import io
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

MAX_XLSX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_XLSX_COLUMNS = 64

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REF = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


class XlsxError(ValueError):
    pass


def _column_name(index):
    result = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _column_index(cell_ref):
    match = _CELL_REF.match(cell_ref or "")
    if not match:
        raise XlsxError("Referência de célula XLSX inválida.")
    letters = match.group(1)
    value = 0
    for letter in letters:
        value = value * 26 + (ord(letter) - 64)
    if value > MAX_XLSX_COLUMNS:
        raise XlsxError("Arquivo XLSX excede o limite de colunas.")
    return value - 1


def _safe_text(value):
    text = "" if value is None else str(value)
    if any(char in text for char in ("\x00",)):
        raise XlsxError("Conteúdo XLSX contém caractere inválido.")
    return text


def build_xlsx(*, headers, rows):
    table = [tuple(_safe_text(value) for value in headers)]
    table.extend(tuple(_safe_text(value) for value in row) for row in rows)
    if any(len(row) > MAX_XLSX_COLUMNS for row in table):
        raise XlsxError("Tabela excede o limite de colunas XLSX.")

    sheet_rows = []
    for row_number, row in enumerate(table, start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            reference = f"{_column_name(column_number)}{row_number}"
            escaped = escape(value)
            cells.append(
                f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{escaped}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_MAIN_NS}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}">'
        '<sheets><sheet name="Dados" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def _bounded_read(archive, name):
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise XlsxError("Estrutura XLSX obrigatória ausente.") from exc
    if info.file_size > MAX_XLSX_UNCOMPRESSED_BYTES:
        raise XlsxError("Parte XLSX excede o limite descompactado.")
    return archive.read(info)


def _shared_strings(archive):
    try:
        payload = _bounded_read(archive, "xl/sharedStrings.xml")
    except XlsxError:
        return []
    root = ET.fromstring(payload)
    strings = []
    for item in root.findall(f"{{{_MAIN_NS}}}si"):
        pieces = [node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t")]
        strings.append("".join(pieces))
    return strings


def _first_sheet_path(archive):
    workbook = ET.fromstring(_bounded_read(archive, "xl/workbook.xml"))
    sheet = workbook.find(f"{{{_MAIN_NS}}}sheets/{{{_MAIN_NS}}}sheet")
    if sheet is None:
        raise XlsxError("Arquivo XLSX não possui planilha.")
    relation_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
    relations = ET.fromstring(_bounded_read(archive, "xl/_rels/workbook.xml.rels"))
    for relation in relations.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        if relation.attrib.get("Id") != relation_id:
            continue
        target = relation.attrib.get("Target", "")
        if target.startswith("/") or ".." in target.split("/"):
            raise XlsxError("Caminho de planilha XLSX inválido.")
        return f"xl/{target.lstrip('/')}"
    raise XlsxError("Relação da planilha XLSX não encontrada.")


def _cell_value(cell, shared_strings):
    if cell.find(f"{{{_MAIN_NS}}}f") is not None:
        raise XlsxError("Fórmulas não são aceitas na importação XLSX.")
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t"))
    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    value = "" if value_node is None else (value_node.text or "")
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError) as exc:
            raise XlsxError("Shared string XLSX inválida.") from exc
    return value


def parse_xlsx(data, *, max_rows):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise XlsxError("Arquivo XLSX inválido.") from exc
    with archive:
        total_size = sum(info.file_size for info in archive.infolist())
        if total_size > MAX_XLSX_UNCOMPRESSED_BYTES:
            raise XlsxError("Arquivo XLSX excede o limite descompactado.")
        shared_strings = _shared_strings(archive)
        sheet_path = _first_sheet_path(archive)
        root = ET.fromstring(_bounded_read(archive, sheet_path))
        matrix = []
        for row in root.findall(f".//{{{_MAIN_NS}}}row"):
            values = []
            for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                index = _column_index(cell.attrib.get("r", ""))
                while len(values) <= index:
                    values.append("")
                values[index] = _cell_value(cell, shared_strings)
            matrix.append(values)
            if len(matrix) > max_rows + 1:
                raise XlsxError(f"O arquivo excede o limite de {max_rows} linhas.")
        if not matrix:
            raise XlsxError("Arquivo XLSX vazio.")
        width = max(len(row) for row in matrix)
        headers = tuple((matrix[0] + [""] * width)[:width])
        if not all(headers) or len(headers) != len(set(headers)):
            raise XlsxError("Cabeçalho XLSX contém coluna vazia ou duplicada.")
        rows = []
        for raw_row in matrix[1:]:
            padded = (raw_row + [""] * width)[:width]
            rows.append(dict(zip(headers, padded, strict=True)))
        return headers, rows
