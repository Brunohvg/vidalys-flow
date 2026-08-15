import csv
import io
from pathlib import Path

from django.core import signing

from apps.platform.xlsx import XlsxError, parse_xlsx

IMPORT_STAGE_SALT = "vidalys.tabular-import.v1"
IMPORT_STAGE_MAX_AGE_SECONDS = 60 * 60
BLANK_MAPPING = "__blank__"


class TabularImportError(ValueError):
    pass


def parse_uploaded_table(*, uploaded, max_bytes, max_rows):
    if uploaded.size > max_bytes:
        raise TabularImportError(f"O arquivo excede o limite de {max_bytes // (1024 * 1024)} MB.")
    payload = uploaded.read()
    suffix = Path(uploaded.name or "").suffix.lower()
    if suffix == ".csv":
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise TabularImportError("CSV deve usar UTF-8.") from exc
        reader = csv.DictReader(io.StringIO(text))
        headers = tuple(reader.fieldnames or ())
        rows = list(reader)
        if len(rows) > max_rows:
            raise TabularImportError(f"O arquivo excede o limite de {max_rows} linhas.")
    elif suffix == ".xlsx":
        try:
            headers, rows = parse_xlsx(payload, max_rows=max_rows)
        except XlsxError as exc:
            raise TabularImportError(str(exc)) from exc
    else:
        raise TabularImportError("Formato não suportado. Use CSV ou XLSX.")
    if not headers:
        raise TabularImportError("Arquivo sem cabeçalho.")
    if not all(headers) or len(headers) != len(set(headers)):
        raise TabularImportError("Cabeçalho contém coluna vazia ou duplicada.")
    return headers, rows


def dump_stage(*, headers, rows):
    return signing.dumps(
        {"headers": list(headers), "rows": rows},
        salt=IMPORT_STAGE_SALT,
        compress=True,
    )


def load_stage(value):
    try:
        payload = signing.loads(
            value,
            salt=IMPORT_STAGE_SALT,
            max_age=IMPORT_STAGE_MAX_AGE_SECONDS,
        )
    except signing.BadSignature as exc:
        raise TabularImportError("Prévia de importação inválida ou expirada.") from exc
    headers = tuple(payload.get("headers") or ())
    rows = payload.get("rows") or []
    if not headers or not isinstance(rows, list):
        raise TabularImportError("Prévia de importação inválida.")
    return headers, rows


def suggested_mapping(*, canonical_headers, source_headers):
    return {
        header: header if header in source_headers else BLANK_MAPPING
        for header in canonical_headers
    }


def mapping_from_post(*, canonical_headers, source_headers, post):
    allowed = set(source_headers) | {BLANK_MAPPING}
    mapping = {}
    used = set()
    for canonical in canonical_headers:
        source = (post.get(f"map_{canonical}") or BLANK_MAPPING).strip()
        if source not in allowed:
            raise TabularImportError(f"Mapeamento inválido para {canonical}.")
        if source != BLANK_MAPPING:
            if source in used:
                raise TabularImportError("Uma coluna de origem não pode alimentar dois campos canônicos.")
            used.add(source)
        mapping[canonical] = source
    return mapping


def apply_mapping(*, canonical_headers, rows, mapping):
    mapped = []
    for source_row in rows:
        mapped.append(
            {
                canonical: (
                    ""
                    if mapping[canonical] == BLANK_MAPPING
                    else str(source_row.get(mapping[canonical]) or "")
                )
                for canonical in canonical_headers
            }
        )
    return mapped
