import io
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ODS_NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

XLSX_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

SUPPORTED_IDENTIFICACAO_EXTENSIONS = {".ods", ".xlsx", ".xlsm"}


def _normalize_header(value: str) -> str:
    text = str(value or "").strip().lower()
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _extract_identificacao_rows(sheet_name: str, rows):
    required = {"os", "peca", "qtde"}
    extracted = []
    indexes = None

    for values in rows:
        trimmed = [str(cell or "").strip() for cell in values]
        if not any(trimmed):
            continue

        if indexes is None:
            normalized = [_normalize_header(cell) for cell in trimmed]
            found = {}
            for idx, header in enumerate(normalized):
                if header == "os":
                    found["os"] = idx
                elif header == "peca":
                    found["peca"] = idx
                elif header == "qtde":
                    found["qtde"] = idx

            if required.issubset(found):
                indexes = found
            continue

        record = {
            "sheet": sheet_name,
            "os": trimmed[indexes["os"]] if indexes["os"] < len(trimmed) else "",
            "codigo_item": trimmed[indexes["peca"]] if indexes["peca"] < len(trimmed) else "",
            "quantidade_lote": trimmed[indexes["qtde"]] if indexes["qtde"] < len(trimmed) else "",
        }

        if any(record[key] for key in ("os", "codigo_item", "quantidade_lote")):
            extracted.append(record)

    return extracted


def _ods_cell_text(cell) -> str:
    parts = []
    for paragraph in cell.findall(".//text:p", ODS_NS):
        text = "".join(paragraph.itertext()).strip()
        if text:
            parts.append(text)
    return " | ".join(parts)


def _expanded_ods_row(row):
    values = []
    repeated_attr = "{%s}number-columns-repeated" % ODS_NS["table"]
    for cell in row.findall("table:table-cell", ODS_NS):
        repeat = int(cell.attrib.get(repeated_attr, "1"))
        text = _ods_cell_text(cell)
        values.extend([text] * repeat)
    return values


def parse_identificacao_ods(file_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        root = ET.fromstring(archive.read("content.xml"))

    extracted = []
    for table in root.findall(".//table:table", ODS_NS):
        sheet_name = table.attrib.get("{%s}name" % ODS_NS["table"], "")
        rows = [_expanded_ods_row(row) for row in table.findall("table:table-row", ODS_NS)]
        extracted.extend(_extract_identificacao_rows(sheet_name, rows))

    return extracted


def _xlsx_shared_strings(archive: zipfile.ZipFile):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("main:si", XLSX_NS):
        text_nodes = item.findall(".//main:t", XLSX_NS)
        if text_nodes:
            values.append("".join(node.text or "" for node in text_nodes))
        else:
            values.append("".join(item.itertext()).strip())
    return values


def _xlsx_target_path(raw_target: str) -> str:
    target = str(raw_target or "").replace("\\", "/").strip()
    if not target:
        return ""
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def _xlsx_sheet_entries(archive: zipfile.ZipFile):
    workbook_xml = "xl/workbook.xml"
    rels_xml = "xl/_rels/workbook.xml.rels"

    if workbook_xml not in archive.namelist():
        return []

    workbook_root = ET.fromstring(archive.read(workbook_xml))
    rel_map = {}

    if rels_xml in archive.namelist():
        rels_root = ET.fromstring(archive.read(rels_xml))
        for rel in rels_root.findall("{%s}Relationship" % XLSX_NS["pkgrel"]):
            rel_map[rel.attrib.get("Id", "")] = _xlsx_target_path(rel.attrib.get("Target", ""))

    sheets = []
    rel_attr = "{%s}id" % XLSX_NS["rel"]
    for sheet in workbook_root.findall("main:sheets/main:sheet", XLSX_NS):
        name = sheet.attrib.get("name", "")
        target = rel_map.get(sheet.attrib.get(rel_attr, ""))
        if target and target in archive.namelist():
            sheets.append((name, target))

    if sheets:
        return sheets

    fallback = []
    for name in sorted(item for item in archive.namelist() if item.startswith("xl/worksheets/") and item.endswith(".xml")):
        fallback.append((Path(name).stem, name))
    return fallback


def _xlsx_column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", str(cell_ref or "").upper())
    if not match:
        return -1

    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _xlsx_cell_text(cell, shared_strings) -> str:
    cell_type = cell.attrib.get("t", "")

    if cell_type == "inlineStr":
        text_nodes = cell.findall(".//main:t", XLSX_NS)
        return "".join(node.text or "" for node in text_nodes).strip()

    value_node = cell.find("main:v", XLSX_NS)
    if value_node is None or value_node.text is None:
        return ""

    raw_value = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except Exception:
            return ""

    return raw_value


def _xlsx_sheet_rows(sheet_bytes: bytes, shared_strings):
    root = ET.fromstring(sheet_bytes)
    for row in root.findall(".//main:sheetData/main:row", XLSX_NS):
        values_by_index = {}
        max_index = -1

        for cell in row.findall("main:c", XLSX_NS):
            index = _xlsx_column_index(cell.attrib.get("r", ""))
            if index < 0:
                index = max_index + 1
            values_by_index[index] = _xlsx_cell_text(cell, shared_strings)
            max_index = max(max_index, index)

        if max_index < 0:
            yield []
            continue

        yield [values_by_index.get(index, "") for index in range(max_index + 1)]


def parse_identificacao_xlsx(file_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        extracted = []

        for sheet_name, target in _xlsx_sheet_entries(archive):
            extracted.extend(
                _extract_identificacao_rows(
                    sheet_name,
                    _xlsx_sheet_rows(archive.read(target), shared_strings),
                )
            )

    return extracted


def parse_identificacao_spreadsheet(file_bytes: bytes, filename: str):
    suffix = Path(str(filename or "").strip()).suffix.lower()
    if suffix == ".ods":
        return parse_identificacao_ods(file_bytes)
    if suffix in {".xlsx", ".xlsm"}:
        return parse_identificacao_xlsx(file_bytes)
    raise ValueError("Formato de planilha não suportado.")
