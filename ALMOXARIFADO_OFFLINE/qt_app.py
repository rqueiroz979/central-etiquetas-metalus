import atexit
import csv
import io
import json
import os
import posixpath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, QSizeF, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QIcon, QKeySequence, QPageSize, QPainter, QPixmap, QShortcut
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import (
    get_lookup_counts,
    init_db,
    list_materials_paginated,
    list_suppliers_paginated,
    lookup_material,
    lookup_supplier,
    normalize_code,
    seed_lookup_data,
    upsert_material,
    upsert_supplier,
)
from pdf_label import generate_label_pdf


APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT))
if os.name == "nt" and (
    not getattr(sys, "frozen", False) or (APP_ROOT / "portable.flag").exists()
):
    APP_DATA_DIR = APP_ROOT
elif os.name == "nt":
    APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Almoxarifado"
else:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    data_root = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    APP_DATA_DIR = data_root / "Almoxarifado"
CONFIG_PATH = APP_DATA_DIR / "config.json"
DEFAULT_CONFIG_PATH = RESOURCE_ROOT / "config.json"
DEFAULT_DB_PATH = APP_DATA_DIR / "data" / "etiquetas.db"
SESSION_OUTPUT_DIR = Path(tempfile.mkdtemp(prefix="almoxarifado_offline-"))


def cleanup_session_output():
    shutil.rmtree(SESSION_OUTPUT_DIR, ignore_errors=True)


atexit.register(cleanup_session_output)

ODS_NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

XLSX_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

MODELS = {
    "Matéria-Prima": {"layout_mode": "a4_12", "label_profile": "materia_prima"},
    "Matéria-Prima Usinados": {"layout_mode": "a4_12", "label_profile": "usinados"},
    "Bens de Consumo": {"layout_mode": "a4_12", "label_profile": "bens_consumo"},
}

PRINT_FORMATS = {
    "Matéria-Prima": {
        "A4 - 8 etiquetas (90 x 60 mm)": "a4_12",
        "Etiqueta 100 x 70 mm": "label_100x70",
    },
    "Matéria-Prima Usinados": {
        "A4 - 8 etiquetas (90 x 60 mm)": "a4_12",
        "Etiqueta 100 x 70 mm": "label_100x70",
    },
    "Bens de Consumo": {
        "A4 - 8 etiquetas (90 x 60 mm)": "a4_12",
        "Etiqueta 100 x 70 mm": "label_100x70",
    },
}

MAX_LABEL_COPIES = 300
MAX_QUANTITY = 2_147_483_647


def parse_quantity(value, field_name):
    text = str("" if value is None else value).strip()
    if text.isascii() and text.isdigit():
        return int(text)
    if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{3})+", text):
        return int(text.replace(".", ""))
    raise ValueError(
        f"{field_name}: informe uma quantidade inteira, sem casas decimais "
        "ou com ponto para separar milhares (exemplo: 1.000)."
    )


LIGHT = {
    "bg": "#f3f4f6",
    "shell": "#ffffff",
    "card": "#ffffff",
    "soft": "#f8fafc",
    "text": "#111827",
    "title": "#0f172a",
    "muted": "#64748b",
    "border": "#d1d5db",
    "accent": "#b91c1c",
    "accent_hover": "#991b1b",
    "input": "#ffffff",
    "table_head": "#eef2f7",
}

class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.finished.emit(self.fn(*self.args, **self.kwargs))
        except Exception as exc:
            self.signals.failed.emit(str(exc))


def load_config():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists() and DEFAULT_CONFIG_PATH.exists():
        shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def path_from_config(config, key, fallback):
    value = str(config.get(key) or "").strip()
    path = Path(value) if value else fallback
    return path if path.is_absolute() else APP_DATA_DIR / path


def app_icon_path():
    icon_path = APP_ROOT / "static" / "almoxarifado.ico"
    if icon_path.exists():
        return icon_path
    return RESOURCE_ROOT / "static" / "almoxarifado.ico"


def open_file(path: Path):
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - user opens a local generated file.
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path)])


def print_pdf(path: Path):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setFullPage(True)

    document = QPdfDocument()
    error = document.load(str(path))
    if error != QPdfDocument.Error.None_:
        raise RuntimeError("Não foi possível carregar o PDF para impressão.")

    if document.pageCount() > 0:
        page_points = document.pagePointSize(0)
        if page_points.isValid() and page_points.width() > 0 and page_points.height() > 0:
            page_mm = QSizeF(page_points.width() * 25.4 / 72, page_points.height() * 25.4 / 72)
            printer.setPageSize(QPageSize(page_mm, QPageSize.Unit.Millimeter, "Etiqueta"))

    dialog = QPrintDialog(printer)
    dialog.setWindowTitle("Imprimir etiqueta")
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("Não foi possível iniciar a impressão.")

    try:
        render_dpi = min(max(printer.resolution(), 150), 300)
        for page in range(document.pageCount()):
            if page > 0 and not printer.newPage():
                raise RuntimeError("Não foi possível criar nova página de impressão.")

            page_points = document.pagePointSize(page)
            image_size = QSize(
                max(1, int(page_points.width() / 72 * render_dpi)),
                max(1, int(page_points.height() / 72 * render_dpi)),
            )
            image = document.render(page, image_size)
            if image.isNull():
                raise RuntimeError("Não foi possível renderizar o PDF para impressão.")

            target = printer.pageRect(QPrinter.Unit.DevicePixel)
            if target.isEmpty():
                target = printer.paperRect(QPrinter.Unit.DevicePixel)

            target_x = int(round(target.x()))
            target_y = int(round(target.y()))
            target_w = int(round(target.width()))
            target_h = int(round(target.height()))
            scaled = image.size().scaled(QSize(target_w, target_h), Qt.AspectRatioMode.KeepAspectRatio)
            draw_rect = QRect(
                target_x + (target_w - scaled.width()) // 2,
                target_y + (target_h - scaled.height()) // 2,
                scaled.width(),
                scaled.height(),
            )
            painter.drawImage(draw_rect, image)
    finally:
        painter.end()

    return True


def normalize_header(value):
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.replace("-", "_").replace(" ", "_")


def decode_csv_bytes(file_bytes):
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def extract_value(row, field_map, aliases):
    for alias in aliases:
        header = field_map.get(normalize_header(alias))
        if header is not None:
            value = row.get(header)
            if value is not None:
                return str(value).strip()
    return ""


MATERIAL_CODE_ALIASES = [
    "codigo_material",
    "código_material",
    "codigo_produto",
    "código_produto",
    "codigo item",
    "código item",
    "cod material",
    "cod_material",
    "cod produto",
    "cod_produto",
    "codigo",
    "código",
    "cod",
]

MATERIAL_DESC_ALIASES = [
    "descricao",
    "descrição",
    "descricao_produto",
    "descrição_produto",
    "descricao_material",
    "descrição_material",
    "produto",
    "material",
    "nome_material",
]

SUPPLIER_CODE_ALIASES = [
    "codigo_fornecedor",
    "código_fornecedor",
    "fornecedor_codigo",
    "fornecedor_código",
    "codigo fornecedor",
    "código fornecedor",
    "cod_fornecedor",
    "cod fornecedor",
]

SUPPLIER_NAME_ALIASES = [
    "nome_fornecedor",
    "fornecedor_nome",
    "fornecedor",
    "razao_social",
    "razão_social",
    "nome",
]


MATERIAL_CODE_ALIASES.extend([
    "codigo_do_produto",
    "codigo do produto",
    "codigo_do_item",
    "codigo do item",
    "cod_item",
])
MATERIAL_DESC_ALIASES.extend([
    "descricao_do_produto",
    "descricao do produto",
    "descricao_do_material",
    "descricao do material",
])
SUPPLIER_CODE_ALIASES.extend([
    "codigo_do_fornecedor",
    "codigo do fornecedor",
])
SUPPLIER_NAME_ALIASES.extend([
    "nome_do_fornecedor",
    "nome do fornecedor",
])


def header_score(headers):
    field_map = {normalize_header(header): header for header in headers}
    score = 0
    for aliases in (MATERIAL_CODE_ALIASES, MATERIAL_DESC_ALIASES, SUPPLIER_CODE_ALIASES, SUPPLIER_NAME_ALIASES):
        if any(normalize_header(alias) in field_map for alias in aliases):
            score += 1
    return score


def dicts_from_rows(rows):
    clean_rows = []
    for raw_row in rows:
        row = [str(value or "").strip() for value in raw_row]
        if any(row):
            clean_rows.append(row)

    if not clean_rows:
        return [], []

    header_index = 0
    best_score = -1
    for index, row in enumerate(clean_rows[:30]):
        score = header_score(row)
        if score > best_score:
            header_index = index
            best_score = score
        if score >= 2:
            break

    headers = clean_rows[header_index]
    output = []
    for row in clean_rows[header_index + 1 :]:
        padded = row + [""] * max(0, len(headers) - len(row))
        output.append({header: padded[index] if index < len(padded) else "" for index, header in enumerate(headers)})
    return headers, output


def dict_groups_from_tables(tables):
    groups = []
    for table_name, rows in tables:
        headers, output = dicts_from_rows(rows)
        if headers and output:
            groups.append((table_name, headers, output))
    return groups


def csv_rows(file_bytes: bytes):
    text = decode_csv_bytes(file_bytes)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except Exception:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    return dicts_from_rows(list(reader))


def csv_tables(file_bytes: bytes):
    headers, rows = csv_rows(file_bytes)
    return [("", headers, rows)] if headers else []


def ods_cell_text(cell):
    parts = []
    for paragraph in cell.findall(".//text:p", ODS_NS):
        text = "".join(paragraph.itertext()).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def ods_rows(file_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    rows = []
    repeated_attr = "{%s}number-columns-repeated" % ODS_NS["table"]
    for table in root.findall(".//table:table", ODS_NS):
        for row_node in table.findall("table:table-row", ODS_NS):
            values = []
            for cell in row_node.findall("table:table-cell", ODS_NS):
                repeat = int(cell.attrib.get(repeated_attr, "1"))
                if repeat > 50:
                    repeat = 1
                values.extend([ods_cell_text(cell)] * repeat)
            rows.append(values)
    return dicts_from_rows(rows)


def ods_tables(file_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    repeated_attr = "{%s}number-columns-repeated" % ODS_NS["table"]
    name_attr = "{%s}name" % ODS_NS["table"]
    tables = []
    for table in root.findall(".//table:table", ODS_NS):
        table_name = table.attrib.get(name_attr, "")
        rows = []
        for row_node in table.findall("table:table-row", ODS_NS):
            values = []
            for cell in row_node.findall("table:table-cell", ODS_NS):
                repeat = int(cell.attrib.get(repeated_attr, "1"))
                if repeat > 50:
                    repeat = 1
                values.extend([ods_cell_text(cell)] * repeat)
            rows.append(values)
        tables.append((table_name, rows))
    return dict_groups_from_tables(tables)


def xlsx_shared_strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("main:si", XLSX_NS):
        texts = item.findall(".//main:t", XLSX_NS)
        values.append("".join(node.text or "" for node in texts).strip() if texts else "".join(item.itertext()).strip())
    return values


def xlsx_target_path(raw_target):
    target = str(raw_target or "").replace("\\", "/").strip()
    if not target:
        return ""
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def xlsx_sheet_entries(archive):
    if "xl/workbook.xml" not in archive.namelist():
        return []
    workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = {}
    if "xl/_rels/workbook.xml.rels" in archive.namelist():
        rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for rel in rels_root.findall("{%s}Relationship" % XLSX_NS["pkgrel"]):
            rels[rel.attrib.get("Id", "")] = _xlsx_target_path_safe(rel.attrib.get("Target", ""))
    rel_attr = "{%s}id" % XLSX_NS["rel"]
    sheets = []
    for sheet in workbook_root.findall("main:sheets/main:sheet", XLSX_NS):
        target = rels.get(sheet.attrib.get(rel_attr, ""))
        if target and target in archive.namelist():
            sheets.append(target)
    if sheets:
        return sheets
    return sorted(item for item in archive.namelist() if item.startswith("xl/worksheets/") and item.endswith(".xml"))


def _xlsx_target_path_safe(raw_target):
    return xlsx_target_path(raw_target)


def xlsx_column_index(cell_ref):
    letters = ""
    for char in str(cell_ref or "").upper():
        if not char.isalpha():
            break
        letters += char
    if not letters:
        return -1
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return index - 1


def xlsx_cell_text(cell, shared_strings):
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//main:t", XLSX_NS)).strip()
    value_node = cell.find("main:v", XLSX_NS)
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw)].strip()
        except Exception:
            return ""
    return raw


def xlsx_rows(file_bytes: bytes):
    rows = []
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        shared_strings = xlsx_shared_strings(archive)
        for sheet_path in xlsx_sheet_entries(archive):
            root = ET.fromstring(archive.read(sheet_path))
            for row_node in root.findall(".//main:sheetData/main:row", XLSX_NS):
                values_by_index = {}
                max_index = -1
                for cell in row_node.findall("main:c", XLSX_NS):
                    index = xlsx_column_index(cell.attrib.get("r", ""))
                    if index < 0:
                        index = max_index + 1
                    values_by_index[index] = xlsx_cell_text(cell, shared_strings)
                    max_index = max(max_index, index)
                if max_index >= 0:
                    rows.append([values_by_index.get(index, "") for index in range(max_index + 1)])
    return dicts_from_rows(rows)


def xlsx_tables(file_bytes: bytes):
    tables = []
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        shared_strings = xlsx_shared_strings(archive)
        for sheet_path in xlsx_sheet_entries(archive):
            rows = []
            root = ET.fromstring(archive.read(sheet_path))
            for row_node in root.findall(".//main:sheetData/main:row", XLSX_NS):
                values_by_index = {}
                max_index = -1
                for cell in row_node.findall("main:c", XLSX_NS):
                    index = xlsx_column_index(cell.attrib.get("r", ""))
                    if index < 0:
                        index = max_index + 1
                    values_by_index[index] = xlsx_cell_text(cell, shared_strings)
                    max_index = max(max_index, index)
                if max_index >= 0:
                    rows.append([values_by_index.get(index, "") for index in range(max_index + 1)])
            tables.append((Path(sheet_path).stem, rows))
    return dict_groups_from_tables(tables)


def spreadsheet_rows(filename: str, file_bytes: bytes):
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return csv_rows(file_bytes)
    if suffix == ".ods":
        return ods_rows(file_bytes)
    if suffix in {".xlsx", ".xlsm"}:
        return xlsx_rows(file_bytes)
    raise ValueError("Formato não suportado.")


def spreadsheet_tables(filename: str, file_bytes: bytes):
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return csv_tables(file_bytes)
    if suffix == ".ods":
        return ods_tables(file_bytes)
    if suffix in {".xlsx", ".xlsm"}:
        return xlsx_tables(file_bytes)
    raise ValueError("Formato nao suportado.")


def existing_codes(conn, table: str, codes):
    found = set()
    code_list = list(codes)
    for index in range(0, len(code_list), 500):
        chunk = code_list[index : index + 500]
        placeholders = ",".join("?" for _ in chunk)
        query = f"SELECT code FROM {table} WHERE code IN ({placeholders})"
        found.update(row[0] for row in conn.execute(query, tuple(chunk)))
    return found


def import_lookup_table(db_path: Path, filename: str, file_bytes: bytes):
    groups = spreadsheet_tables(filename, file_bytes)
    if not groups:
        raise ValueError("Arquivo sem cabecalho.")

    materials_to_save = {}
    suppliers_to_save = {}
    materials = 0
    suppliers = 0
    ignored = 0

    for table_name, fieldnames, rows in groups:
        field_map = {normalize_header(header): header for header in fieldnames}
        table_hint = normalize_header(table_name)
        supplier_sheet = "fornecedor" in table_hint or "supplier" in table_hint
        material_sheet = "material" in table_hint or "produto" in table_hint

        for row in rows:
            material_code = normalize_code(extract_value(row, field_map, MATERIAL_CODE_ALIASES))
            material_desc = extract_value(row, field_map, MATERIAL_DESC_ALIASES)
            supplier_code = normalize_code(extract_value(row, field_map, SUPPLIER_CODE_ALIASES))
            supplier_name = extract_value(row, field_map, SUPPLIER_NAME_ALIASES)

            generic_code = normalize_code(extract_value(row, field_map, ["codigo", "cod"]))
            generic_name = extract_value(row, field_map, ["nome", "razao_social", "fornecedor"])
            if supplier_sheet and not supplier_code and generic_code:
                supplier_code = generic_code
            if supplier_sheet and not supplier_name and generic_name:
                supplier_name = generic_name
            if material_sheet and not material_code and generic_code:
                material_code = generic_code
            if material_sheet and not material_desc:
                material_desc = extract_value(row, field_map, ["descricao", "produto", "material", "nome"])
            if not supplier_code and not material_desc and generic_code and generic_name:
                supplier_code = generic_code
                supplier_name = generic_name

            changed = False
            if material_code and material_desc:
                materials_to_save[material_code] = material_desc
                materials += 1
                changed = True
            if supplier_code and supplier_name:
                suppliers_to_save[supplier_code] = supplier_name
                suppliers += 1
                changed = True
            if not changed:
                ignored += 1

    if materials == 0 and suppliers == 0:
        raise ValueError(
            "Nenhum material ou fornecedor foi importado. "
            "Use colunas como codigo_material/descricao ou codigo_fornecedor/nome_fornecedor."
        )

    conn = sqlite3.connect(db_path)
    try:
        material_codes = set(materials_to_save)
        supplier_codes = set(suppliers_to_save)
        existing_materials = set()
        existing_suppliers = set()
        if material_codes:
            existing_materials = existing_codes(conn, "materials", material_codes)
        if supplier_codes:
            existing_suppliers = existing_codes(conn, "suppliers", supplier_codes)
        if materials_to_save:
            conn.executemany(
                "INSERT OR REPLACE INTO materials (code, description) VALUES (?, ?)",
                list(materials_to_save.items()),
            )
        if suppliers_to_save:
            conn.executemany(
                "INSERT OR REPLACE INTO suppliers (code, name) VALUES (?, ?)",
                list(suppliers_to_save.items()),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    material_updates = len(existing_materials)
    material_new = len(materials_to_save) - material_updates
    supplier_updates = len(existing_suppliers)
    supplier_new = len(suppliers_to_save) - supplier_updates

    return (
        "Importação concluída com sucesso. "
        f"Materiais: {material_new} novos e {material_updates} atualizados. "
        f"Fornecedores: {supplier_new} novos e {supplier_updates} atualizados. "
        f"{ignored} linhas ignoradas."
    )


def import_lookup_file(db_path: Path, filename: str):
    return import_lookup_table(db_path, filename, Path(filename).read_bytes())


def generate_pdf_task(db_path, output_dir, logo_path, payload, copies, layout_mode):
    pdf_path = generate_label_pdf(
        output_dir=output_dir,
        logo_path=logo_path,
        payload=payload,
        copies=copies,
        layout_mode=layout_mode,
    )
    return pdf_path


def lookup_counts_task(db_path):
    return get_lookup_counts(db_path)


def load_lookup_page_task(db_path, section, search, page, per_page):
    if section == "materials":
        return list_materials_paginated(db_path, search=search, page=page, per_page=per_page)
    return list_suppliers_paginated(db_path, search=search, page=page, per_page=per_page)


def lookup_form_data_task(db_path, material_code, supplier_code):
    return {
        "material_code": material_code,
        "material_desc": lookup_material(db_path, material_code) if material_code else "",
        "supplier_code": supplier_code,
        "supplier_name": lookup_supplier(db_path, supplier_code) if supplier_code else "",
    }


def qss(colors):
    return f"""
    QMainWindow, QWidget#root {{
        background: {colors["bg"]};
    }}
    QFrame#shell {{
        background: {colors["shell"]};
        border: 1px solid {colors["border"]};
        border-radius: 24px;
    }}
    QFrame[class="card"] {{
        background: {colors["card"]};
        border: 1px solid {colors["border"]};
        border-radius: 20px;
    }}
    QFrame[class="soft"] {{
        background: {colors["soft"]};
        border: 1px solid {colors["border"]};
        border-radius: 18px;
    }}
    QLabel {{
        color: {colors["text"]};
        font-size: 14px;
    }}
    QLabel[class="title"] {{
        color: {colors["title"]};
        font-size: 44px;
        font-weight: 800;
        letter-spacing: 0px;
    }}
    QLabel[class="h1"] {{
        color: {colors["title"]};
        font-size: 23px;
        font-weight: 800;
    }}
    QLabel[class="h2"] {{
        color: {colors["title"]};
        font-size: 16px;
        font-weight: 800;
    }}
    QLabel[class="field"] {{
        color: {colors["muted"]};
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel[class="muted"] {{
        color: {colors["muted"]};
        font-size: 12px;
    }}
    QLabel[class="eyebrow"] {{
        color: {colors["accent"]};
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0px;
    }}
    QLabel#logoBox {{
        background: white;
        border: 1px solid {colors["border"]};
        border-radius: 16px;
        padding: 8px;
    }}
    QLineEdit, QComboBox, QSpinBox {{
        color: {colors["text"]};
        background: {colors["input"]};
        border: 1px solid {colors["border"]};
        border-radius: 7px;
        padding: 8px 10px;
        min-height: 20px;
        }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {colors["accent"]};
    }}
    QLineEdit[autoFill="true"] {{
        background: {colors["soft"]};
        border-style: dashed;
    }}
    QComboBox::drop-down {{
        border: 0;
        width: 30px;
    }}
    QComboBox QAbstractItemView {{
        color: {colors["text"]};
        background: {colors["input"]};
        border: 1px solid {colors["border"]};
        selection-background-color: {colors["accent"]};
        selection-color: white;
        outline: 0;
        padding: 4px;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 26px;
        padding: 6px 10px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 26px;
        border: 0;
    }}
    QPushButton {{
        color: {colors["text"]};
        background: {colors["soft"]};
        border: 1px solid {colors["border"]};
        border-radius: 7px;
        padding: 8px 13px;
        font-weight: 700;
    }}
    QPushButton:hover {{
        border-color: {colors["accent"]};
    }}
    QPushButton[class="primary"] {{
        background: {colors["accent"]};
        color: white;
        border: 0;
    }}
    QPushButton[class="primary"]:hover {{
        background: {colors["accent_hover"]};
    }}
    QPushButton[class="tabActive"] {{
        background: {colors["accent"]};
        color: white;
        border: 0;
    }}
    QPushButton[class="tabInactive"] {{
        background: {colors["soft"]};
        color: {colors["text"]};
    }}
    QPushButton[class="selector"] {{
        background: {colors["card"]};
        color: {colors["accent"]};
        border: 1px solid {colors["accent"]};
        padding-left: 12px;
        padding-right: 12px;
    }}
    QScrollArea {{
        background: transparent;
        border: 0;
    }}
    QTableWidget {{
        color: {colors["text"]};
        background: {colors["input"]};
        border: 1px solid {colors["border"]};
        border-radius: 7px;
        gridline-color: {colors["border"]};
        selection-background-color: {colors["accent"]};
        selection-color: white;
    }}
    QHeaderView::section {{
        background: {colors["table_head"]};
        border: 0;
        padding: 10px;
        color: {colors["muted"]};
        font-weight: 800;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {colors["border"]};
        border-radius: 5px;
    }}
    QMessageBox {{
        background: {colors["card"]};
    }}
    QMessageBox QLabel {{
        color: {colors["text"]};
        font-size: 13px;
    }}
    QMessageBox QPushButton {{
        min-width: 72px;
    }}
    """


class LookupDialog(QDialog):
    def __init__(self, parent, title, value_header, loader):
        super().__init__(parent)
        self.setWindowTitle(title)
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(
                min(760, int(available.width() * 0.95)),
                min(520, int(available.height() * 0.9)),
            )
        else:
            self.resize(760, 520)
        self.loader = loader
        self.page = 1
        self.pages = 1
        self.selected = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        title_label = QLabel(title)
        title_label.setProperty("class", "h1")
        layout.addWidget(title_label)

        search_line = QHBoxLayout()
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Buscar por código ou descrição")
        search_btn = QPushButton("Buscar")
        search_btn.clicked.connect(self.search)
        search_line.addWidget(self.search_entry, 1)
        search_line.addWidget(search_btn)
        layout.addLayout(search_line)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["CÓDIGO", value_header])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.doubleClicked.connect(self.accept_selected)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.page_label = QLabel("")
        prev_btn = QPushButton("Anterior")
        next_btn = QPushButton("Próxima")
        choose_btn = QPushButton("Selecionar")
        choose_btn.setProperty("class", "primary")
        prev_btn.clicked.connect(self.prev_page)
        next_btn.clicked.connect(self.next_page)
        choose_btn.clicked.connect(self.accept_selected)
        footer.addWidget(prev_btn)
        footer.addWidget(self.page_label)
        footer.addWidget(next_btn)
        footer.addStretch()
        footer.addWidget(choose_btn)
        layout.addLayout(footer)

        self.load()

    def search(self):
        self.page = 1
        self.load()

    def load(self):
        data = self.loader(self.search_entry.text().strip(), self.page, 10)
        self.pages = data["pages"]
        self.table.setRowCount(0)
        for item in data["items"]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item["code"]))
            self.table.setItem(row, 1, QTableWidgetItem(item["label"]))
        self.page_label.setText(f"Página {data['page']} de {data['pages']}")

    def prev_page(self):
        if self.page > 1:
            self.page -= 1
            self.load()

    def next_page(self):
        if self.page < self.pages:
            self.page += 1
            self.load()

    def accept_selected(self, _index=None):
        row = self.table.currentRow()
        if row < 0:
            return
        self.selected = {
            "code": self.table.item(row, 0).text(),
            "label": self.table.item(row, 1).text(),
        }
        self.accept()


class PdfPreviewDialog(QDialog):
    def __init__(self, parent, pdf_path: Path):
        super().__init__(parent)
        self.pdf_path = Path(pdf_path)
        self.setWindowTitle(f"Visualizar etiqueta - {self.pdf_path.name}")
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            min_width = min(700, available.width())
            min_height = min(560, available.height())
            self.setMinimumSize(min_width, min_height)
            self.resize(
                max(min_width, min(980, int(available.width() * 0.95))),
                max(min_height, min(720, int(available.height() * 0.9))),
            )
        else:
            self.resize(980, 720)
            self.setMinimumSize(700, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        header = QHBoxLayout()
        title = QLabel("Visualizador de PDF")
        title.setProperty("class", "h1")
        filename = QLabel(self.pdf_path.name)
        filename.setProperty("class", "muted")
        title_box = QVBoxLayout()
        title_box.addWidget(title)
        title_box.addWidget(filename)
        header.addLayout(title_box, 1)

        print_btn = QPushButton("Imprimir")
        print_btn.setProperty("class", "primary")
        save_btn = QPushButton("Salvar como")
        open_btn = QPushButton("Abrir externo")
        close_btn = QPushButton("Fechar")
        print_btn.clicked.connect(self.print_current)
        save_btn.clicked.connect(self.save_as)
        open_btn.clicked.connect(lambda: open_file(self.pdf_path))
        close_btn.clicked.connect(self.accept)
        header.addWidget(print_btn)
        header.addWidget(save_btn)
        header.addWidget(open_btn)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self.document = QPdfDocument(self)
        self.document.load(str(self.pdf_path))
        self.viewer = QPdfView()
        self.viewer.setDocument(self.document)
        try:
            self.viewer.setZoomMode(QPdfView.ZoomMode.FitInView)
        except Exception:
            pass
        layout.addWidget(self.viewer, 1)

    def print_current(self):
        try:
            print_pdf(self.pdf_path)
        except Exception as exc:
            QMessageBox.warning(self, "Imprimir", f"Não foi possível enviar para impressão.\n\n{exc}")

    def save_as(self):
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar etiqueta",
            str(APP_DATA_DIR / self.pdf_path.name),
            "PDF (*.pdf)",
        )
        if not target:
            return
        target_path = Path(target)
        if target_path.suffix.lower() != ".pdf":
            target_path = target_path.with_suffix(".pdf")
        try:
            shutil.copy2(self.pdf_path, target_path)
        except Exception as exc:
            QMessageBox.warning(self, "Salvar como", f"Não foi possível salvar o PDF.\n\n{exc}")
            return
        QMessageBox.information(self, "Salvar como", "PDF salvo.")


class AlmoxarifadoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ALMOXARIFADO")
        icon_path = app_icon_path()
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.content_scale = min(1.0, max(0.5, available.width() / 960))
            min_width = min(720, max(1, available.width() - 32))
            min_height = min(620, max(1, available.height() - 32))
            self.setMinimumSize(min_width, min_height)
            self.resize(
                max(min_width, min(1040, int(available.width() * 0.95))),
                max(min_height, min(820, int(available.height() * 0.92))),
            )
        else:
            self.content_scale = 1.0
            self.resize(1040, 820)
            self.setMinimumSize(720, 620)

        config = load_config()
        self.db_path = path_from_config(config, "db_path", DEFAULT_DB_PATH)
        self.output_dir = SESSION_OUTPUT_DIR
        self.logo_path = APP_ROOT / "static" / "logo-metalus.png"
        if not self.logo_path.exists():
            self.logo_path = RESOURCE_ROOT / "static" / "logo-metalus.png"
        if not self.logo_path.exists():
            self.logo_path = APP_ROOT / "static" / "LOGO METALUS.png"
        if not self.logo_path.exists():
            self.logo_path = RESOURCE_ROOT / "static" / "LOGO METALUS.png"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        init_db(self.db_path)
        seed_lookup_data(self.db_path, RESOURCE_ROOT / "seed" / "lookups.db")

        self.thread_pool = QThreadPool.globalInstance()
        self.last_pdf_path = None
        self.entries = {}
        self.cadastro_section = "materials"
        self.cadastro_page = 1
        self.cadastro_pages = 1
        self.compact_mode = None
        self.zoom_factor = 1.0
        self.scaled_shells = []
        self.counts_worker = None
        self.cadastros_worker = None
        self.cadastros_request_id = 0
        self.lookup_worker = None
        self.lookup_request_id = 0
        self.lookup_timer = QTimer(self)
        self.lookup_timer.setSingleShot(True)
        self.lookup_timer.setInterval(180)
        self.lookup_timer.timeout.connect(self.lookup_data)

        self.stack = QStackedWidget()
        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.setCentralWidget(root)

        self.home_page = self.build_home_page()
        self.cadastros_page = self.build_cadastros_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.cadastros_page)
        self.refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self.refresh_shortcut.activated.connect(self.refresh_current_view)
        self.apply_theme()
        self.set_cadastro_section("materials", load=False)
        self.apply_zoom()
        self.update_responsive_layout()
        QTimer.singleShot(0, self.initial_background_load)

    def apply_theme(self):
        self.setUpdatesEnabled(False)
        self.setStyleSheet(qss(LIGHT))
        self.setUpdatesEnabled(True)

    def set_zoom(self, value):
        text = str(value).replace("%", "").strip()
        try:
            self.zoom_factor = max(0.85, min(1.35, int(text) / 100))
        except ValueError:
            self.zoom_factor = 1.0
        self.apply_zoom()

    def apply_zoom(self):
        width = int(1180 * self.zoom_factor * self.content_scale)
        min_width = int(660 * self.zoom_factor * self.content_scale)
        for shell in self.scaled_shells:
            shell.setMinimumWidth(min_width)
            shell.setMaximumWidth(width)
        self.update_responsive_layout()

    def scaled_width(self, width):
        return int(width * self.content_scale)

    def card(self, class_name="card"):
        frame = QFrame()
        frame.setProperty("class", class_name)
        return frame

    def repolish(self, widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def scroll_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("root")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)
        return scroll

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_responsive_layout()

    def update_responsive_layout(self):
        compact = self.width() < 980
        if compact == self.compact_mode:
            return
        self.compact_mode = compact
        if hasattr(self, "home_bottom_layout"):
            self.home_bottom_layout.setDirection(QHBoxLayout.TopToBottom if compact else QHBoxLayout.LeftToRight)
        if hasattr(self, "cad_cards_layout"):
            self.cad_cards_layout.setDirection(QHBoxLayout.TopToBottom if compact else QHBoxLayout.LeftToRight)
        if hasattr(self, "cad_search_layout"):
            self.cad_search_layout.setDirection(QHBoxLayout.TopToBottom if compact else QHBoxLayout.LeftToRight)

    def initial_background_load(self):
        self.refresh_counts()
        self.load_cadastros()

    def field(self, label, key, parent_layout, row, col, colspan=1, value=""):
        box = QVBoxLayout()
        box.setSpacing(5)
        title = QLabel(label)
        title.setProperty("class", "field")
        entry = QLineEdit()
        entry.setText(value)
        entry.returnPressed.connect(self.focusNextChild)
        self.entries[key] = entry
        box.addWidget(title)
        box.addWidget(entry)
        parent_layout.addLayout(box, row, col, 1, colspan)
        return entry

    def selector_field(self, label, key, button_text, callback, parent_layout, row, col, colspan=1):
        box = QVBoxLayout()
        box.setSpacing(5)
        title = QLabel(label)
        title.setProperty("class", "field")
        line = QHBoxLayout()
        line.setSpacing(8)
        entry = QLineEdit()
        entry.returnPressed.connect(self.focusNextChild)
        button = QPushButton(button_text)
        button.setProperty("class", "selector")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(callback)
        self.entries[key] = entry
        line.addWidget(entry, 1)
        line.addWidget(button)
        box.addWidget(title)
        box.addLayout(line)
        parent_layout.addLayout(box, row, col, 1, colspan)
        return entry

    def build_logo(self, size=120):
        label = QLabel()
        label.setObjectName("logoBox")
        label.setFixedSize(size + 34, size + 18)
        label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(str(self.logo_path))
        if not pixmap.isNull():
            label.setPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            label.setText("METALUS")
        return label

    def build_header(self):
        header = self.card()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(24)
        header.setMinimumWidth(self.scaled_width(640))
        layout.addWidget(self.build_logo(108), 0, Qt.AlignVCenter)

        heading = QVBoxLayout()
        title = QLabel("Almoxarifado")
        title.setProperty("class", "title")
        heading.addStretch()
        heading.addWidget(title)
        heading.addStretch()
        layout.addLayout(heading, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        cad = self.card()
        cad.setMinimumWidth(self.scaled_width(150))
        cad.setCursor(Qt.PointingHandCursor)
        cad.mousePressEvent = lambda _event: self.stack.setCurrentWidget(self.cadastros_page)
        cad_layout = QVBoxLayout(cad)
        cad_layout.setContentsMargins(16, 12, 16, 12)
        cad_layout.setSpacing(7)
        cad_title = QLabel("Cadastros")
        cad_title.setProperty("class", "h2")
        self.counts_label = QLabel("")
        self.counts_label.setProperty("class", "muted")
        open_btn = QPushButton("Abrir")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.cadastros_page))
        cad_layout.addWidget(cad_title)
        cad_layout.addWidget(self.counts_label)
        open_btn.hide()
        right.addWidget(cad)
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.setToolTip("Limpar tela para gerar uma nova etiqueta")
        refresh_btn.clicked.connect(self.refresh_current_view)
        right.addWidget(refresh_btn)
        layout.addLayout(right)
        return header

    def build_home_page(self):
        page = self.scroll_page()
        content = page.widget()
        layout = content.layout()
        layout.setContentsMargins(20, 18, 20, 18)
        shell = QFrame()
        shell.setObjectName("shell")
        shell.setMinimumWidth(self.scaled_width(660))
        shell.setMaximumWidth(self.scaled_width(1180))
        self.scaled_shells.append(shell)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(14, 14, 14, 14)
        shell_layout.setSpacing(12)
        shell_layout.addWidget(self.build_header())

        form = self.card()
        form.setMinimumWidth(self.scaled_width(640))
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(12)
        title = QLabel("Etiqueta de Produção")
        title.setProperty("class", "h1")
        form_layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        model_box = QVBoxLayout()
        model_label = QLabel("Tipo de etiqueta")
        model_label.setProperty("class", "field")
        self.model_combo = QComboBox()
        self.model_combo.addItems(MODELS.keys())
        self.model_combo.currentTextChanged.connect(self.update_print_formats)
        model_box.addWidget(model_label)
        model_box.addWidget(self.model_combo)
        grid.addLayout(model_box, 0, 0, 1, 3)
        self.selector_field("Código do Produto", "codigo", "Selecionar", self.open_material_selector, grid, 0, 3, 4)
        self.field("Data", "data", grid, 0, 7, 2, datetime.now().strftime("%d/%m/%y"))
        self.field("Nº Lote", "lote", grid, 0, 9, 3)
        material_desc = self.field("Descrição do material", "material_desc", grid, 1, 0, 12)
        material_desc.setPlaceholderText("Preenchimento automático ao informar ou selecionar o produto")
        material_desc.setProperty("autoFill", "true")
        self.field("Insp.", "insp", grid, 2, 0, 3)
        self.field("Ref.", "ref", grid, 2, 3, 3, "0,00")
        self.field("Dimensão 1", "dim1", grid, 2, 6, 3, "1200")
        self.field("Dimensão 2", "dim2", grid, 2, 9, 3, "2000")
        self.selector_field("Fornecedor (código)", "fornecedor", "Selecionar", self.open_supplier_selector, grid, 3, 0, 5)
        fornecedor_nome = self.field("Nome do fornecedor", "fornecedor_nome", grid, 3, 5, 7)
        fornecedor_nome.setPlaceholderText("Preenchimento automático ao informar ou selecionar o fornecedor")
        fornecedor_nome.setProperty("autoFill", "true")
        form_layout.addLayout(grid)

        bottom = QHBoxLayout()
        self.home_bottom_layout = bottom
        comp = self.card("soft")
        comp.setMinimumWidth(self.scaled_width(340))
        comp_layout = QGridLayout(comp)
        comp_layout.setContentsMargins(12, 12, 12, 12)
        comp_layout.setHorizontalSpacing(10)
        comp_layout.setVerticalSpacing(10)
        comp_layout.setAlignment(Qt.AlignTop)
        comp_title = QLabel("Dados Complementares")
        comp_title.setProperty("class", "h2")
        comp_layout.addWidget(comp_title, 0, 0, 1, 6)
        self.field("PDC", "pdc", comp_layout, 1, 0, 2)
        self.field("Quant.", "quant", comp_layout, 1, 2, 2)
        self.field("NF", "nf", comp_layout, 1, 4, 2)
        self.field("O.S.", "os", comp_layout, 2, 0, 2)
        self.field("Pallet", "pallet", comp_layout, 2, 2, 2)
        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        left_column.addWidget(comp, 0, Qt.AlignTop)

        print_card = self.card("soft")
        print_card.setMinimumWidth(self.scaled_width(390))
        print_layout = QVBoxLayout(print_card)
        print_layout.setContentsMargins(12, 12, 12, 12)
        print_layout.setSpacing(9)
        print_layout.setAlignment(Qt.AlignTop)
        print_title = QLabel("Configuração de Impressão")
        print_title.setProperty("class", "h2")
        print_layout.addWidget(print_title)
        copies_label = QLabel("Quantidade de etiquetas")
        copies_label.setProperty("class", "field")
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, MAX_LABEL_COPIES)
        self.copies_spin.setValue(1)
        self.copies_spin.setSingleStep(1)
        self.copies_spin.lineEdit().returnPressed.connect(self.focusNextChild)
        self.copies_spin.valueChanged.connect(self.update_pallet_rows)
        print_layout.addWidget(copies_label)
        print_layout.addWidget(self.copies_spin)
        self.pallets_box = self.card("soft")
        pallets_layout = QVBoxLayout(self.pallets_box)
        pallets_layout.setContentsMargins(10, 10, 10, 10)
        pallets_layout.setSpacing(8)
        pallets_title = QLabel("Pallets recebidos")
        pallets_title.setProperty("class", "h2")
        pallets_layout.addWidget(pallets_title)
        self.pallets_hint = QLabel("Preencha a quantidade de cada pallet.")
        self.pallets_hint.setProperty("class", "muted")
        pallets_layout.addWidget(self.pallets_hint)
        auto_line = QHBoxLayout()
        total_label = QLabel("Qtd. total")
        total_label.setProperty("class", "field")
        self.total_received_spin = QSpinBox()
        self.total_received_spin.setRange(0, MAX_QUANTITY)
        self.total_received_spin.setValue(0)
        self.total_received_spin.lineEdit().returnPressed.connect(self.focusNextChild)
        self.total_received_spin.valueChanged.connect(self.sync_quantity_field_from_total_spin)
        divide_btn = QPushButton("Dividir auto.")
        divide_btn.setToolTip("Dividir automaticamente")
        divide_btn.setMinimumWidth(self.scaled_width(120))
        divide_btn.setMaximumWidth(self.scaled_width(140))
        divide_btn.clicked.connect(self.divide_pallet_quantities)
        auto_line.addWidget(total_label)
        auto_line.addWidget(self.total_received_spin, 1)
        auto_line.addWidget(divide_btn)
        pallets_layout.addLayout(auto_line)
        self.pallets_table = QTableWidget(0, 2)
        self.pallets_table.setHorizontalHeaderLabels(["Pallet", "Quantidade"])
        self.pallets_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.pallets_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.pallets_table.verticalHeader().setVisible(False)
        self.pallets_table.setMinimumHeight(150)
        self.pallets_table.itemChanged.connect(self.pallet_quantity_changed)
        pallets_layout.addWidget(self.pallets_table)
        self.pallets_box.hide()
        print_layout.addWidget(self.pallets_box)
        format_label = QLabel("Formato de impressão")
        format_label.setProperty("class", "field")
        self.print_format_combo = QComboBox()
        self.print_format_combo.setMaxVisibleItems(6)
        self.print_format_combo.setMinimumHeight(38)
        print_layout.addWidget(format_label)
        print_layout.addWidget(self.print_format_combo)
        self.generate_btn = QPushButton("Gerar Etiqueta")
        self.generate_btn.setProperty("class", "primary")
        self.generate_btn.setCursor(Qt.PointingHandCursor)
        self.generate_btn.clicked.connect(self.generate_pdf)
        print_layout.addWidget(self.generate_btn)
        last_btn = QPushButton("Abrir último PDF")
        last_btn.clicked.connect(self.open_last_pdf)
        print_layout.addWidget(last_btn)

        self.status_label = QLabel("")
        self.status_label.setProperty("class", "muted")

        self.preview_card = self.card("soft")
        preview_layout = QVBoxLayout(self.preview_card)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(10)
        preview_header = QGridLayout()
        preview_header.setHorizontalSpacing(8)
        preview_header.setVerticalSpacing(6)
        preview_title_box = QVBoxLayout()
        preview_title = QLabel("Visualizador de PDF")
        preview_title.setProperty("class", "h2")
        self.preview_filename = QLabel("")
        self.preview_filename.setProperty("class", "muted")
        preview_title_box.addWidget(preview_title)
        preview_title_box.addWidget(self.preview_filename)
        preview_header.addLayout(preview_title_box, 0, 0, 1, 4)

        zoom_out_btn = QPushButton("-")
        zoom_out_btn.setToolTip("Diminuir zoom")
        zoom_out_btn.setFixedWidth(36)
        zoom_out_btn.clicked.connect(lambda: self.zoom_preview(0.85))
        self.preview_zoom_label = QLabel("100%")
        self.preview_zoom_label.setProperty("class", "muted")
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setToolTip("Aumentar zoom")
        zoom_in_btn.setFixedWidth(36)
        zoom_in_btn.clicked.connect(lambda: self.zoom_preview(1.15))
        fit_btn = QPushButton("Ajustar")
        fit_btn.clicked.connect(self.fit_preview_width)
        print_btn = QPushButton("Imprimir")
        print_btn.setProperty("class", "primary")
        print_btn.clicked.connect(self.print_preview_pdf)
        save_btn = QPushButton("Salvar")
        save_btn.setToolTip("Salvar como")
        save_btn.clicked.connect(self.save_preview_pdf)
        open_btn = QPushButton("Externo")
        open_btn.setToolTip("Abrir externo")
        open_btn.clicked.connect(self.open_preview_external)
        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.close_preview)
        for index, widget in enumerate((zoom_out_btn, self.preview_zoom_label, zoom_in_btn, fit_btn)):
            preview_header.addWidget(widget, 1, index)
        for index, widget in enumerate((print_btn, save_btn, open_btn, close_btn)):
            preview_header.addWidget(widget, 2, index)
        preview_layout.addLayout(preview_header)

        self.preview_document = QPdfDocument(self)
        self.preview_viewer = QPdfView()
        self.preview_viewer.setDocument(self.preview_document)
        self.preview_viewer.setMinimumHeight(280)
        try:
            self.preview_viewer.setPageMode(QPdfView.PageMode.MultiPage)
            self.preview_viewer.setPageSpacing(12)
            self.preview_viewer.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        except Exception:
            pass
        preview_layout.addWidget(self.preview_viewer, 1)
        self.preview_card.hide()
        left_column.addWidget(self.preview_card, 1)
        left_column.addStretch(1)
        bottom.addLayout(left_column, 7)
        bottom.addWidget(print_card, 6, Qt.AlignTop)
        form_layout.addLayout(bottom)
        form_layout.addWidget(self.status_label)

        self.entries["codigo"].textEdited.connect(self.schedule_lookup_data)
        self.entries["fornecedor"].textEdited.connect(self.schedule_lookup_data)
        self.entries["pallet"].textEdited.connect(self.sync_pallet_count_from_field)
        self.copies_spin.valueChanged.connect(self.sync_pallet_field_from_copy_count)
        self.entries["quant"].textEdited.connect(self.sync_total_quantity_from_field)

        shell_layout.addWidget(form, 1)
        layout.addWidget(shell, 0, Qt.AlignHCenter | Qt.AlignTop)
        self.update_print_formats(self.model_combo.currentText())
        return page

    def update_print_formats(self, model_name):
        if not hasattr(self, "print_format_combo"):
            return
        current = self.print_format_combo.currentText()
        self.print_format_combo.blockSignals(True)
        self.print_format_combo.clear()
        formats = PRINT_FORMATS.get(model_name, PRINT_FORMATS["Matéria-Prima"])
        self.print_format_combo.addItems(formats.keys())
        if current in formats:
            self.print_format_combo.setCurrentText(current)
        self.print_format_combo.setEnabled(len(formats) > 1)
        self.print_format_combo.blockSignals(False)

    def build_cadastros_page(self):
        page = self.scroll_page()
        content = page.widget()
        layout = content.layout()
        layout.setContentsMargins(20, 18, 20, 18)
        shell = QFrame()
        shell.setObjectName("shell")
        shell.setMinimumWidth(self.scaled_width(660))
        shell.setMaximumWidth(self.scaled_width(1180))
        self.scaled_shells.append(shell)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(14, 14, 14, 14)
        shell_layout.setSpacing(12)
        top = QHBoxLayout()
        back = QPushButton("← Almoxarifado")
        back.clicked.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        top.addWidget(back)
        top.addStretch()
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.setToolTip("Recarregar lista e contadores")
        refresh_btn.clicked.connect(self.refresh_current_view)
        top.addWidget(refresh_btn)
        shell_layout.addLayout(top)

        head = self.card()
        head.setMinimumWidth(self.scaled_width(640))
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(16, 14, 16, 14)
        head_layout.setSpacing(18)
        head_layout.addWidget(self.build_logo(92))
        texts = QVBoxLayout()
        title = QLabel("Cadastros")
        title.setProperty("class", "h1")
        desc = QLabel("Cadastro de materiais, produtos e fornecedores")
        desc.setProperty("class", "muted")
        self.cad_counts_label = QLabel("")
        self.cad_counts_label.setProperty("class", "muted")
        texts.addWidget(title)
        texts.addWidget(desc)
        texts.addWidget(self.cad_counts_label)
        head_layout.addLayout(texts, 1)
        shell_layout.addWidget(head)

        body = self.card()
        body.setMinimumWidth(self.scaled_width(640))
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 14, 14, 14)
        body_layout.setSpacing(12)
        body_title = QLabel("Cadastros")
        body_title.setProperty("class", "h1")
        body_layout.addWidget(body_title)
        body_layout.addWidget(QLabel("Materiais, produtos e fornecedores usados no preenchimento automático."))
        tabs = QHBoxLayout()
        self.materials_btn = QPushButton("Materiais / Produtos")
        self.suppliers_btn = QPushButton("Fornecedores")
        self.materials_btn.clicked.connect(lambda: self.set_cadastro_section("materials"))
        self.suppliers_btn.clicked.connect(lambda: self.set_cadastro_section("suppliers"))
        tabs.addWidget(self.materials_btn)
        tabs.addWidget(self.suppliers_btn)
        tabs.addStretch()
        body_layout.addLayout(tabs)

        cards = QHBoxLayout()
        self.cad_cards_layout = cards
        import_card = self.card()
        import_card.setMinimumWidth(self.scaled_width(300))
        import_layout = QVBoxLayout(import_card)
        import_layout.setContentsMargins(14, 14, 14, 14)
        import_layout.setSpacing(10)
        imp_title = QLabel("Importar tabela")
        imp_title.setProperty("class", "h2")
        import_layout.addWidget(imp_title)
        import_layout.addWidget(QLabel("CSV, ODS, XLSX ou XLSM com materiais e fornecedores."))
        self.import_file_label = QLabel("Nenhum arquivo selecionado.")
        self.import_file_label.setProperty("class", "muted")
        self.import_file_label.setWordWrap(True)
        import_layout.addWidget(self.import_file_label)
        self.import_result_label = QLabel("")
        self.import_result_label.setProperty("class", "muted")
        self.import_result_label.setWordWrap(True)
        import_layout.addWidget(self.import_result_label)
        self.import_btn = QPushButton("Importar tabela")
        self.import_btn.setProperty("class", "primary")
        self.import_btn.setCursor(Qt.PointingHandCursor)
        self.import_btn.clicked.connect(self.import_file)
        import_layout.addWidget(self.import_btn, 0, Qt.AlignLeft)
        import_layout.addStretch()
        cards.addWidget(import_card)

        edit_card = self.card()
        edit_card.setMinimumWidth(self.scaled_width(300))
        edit_layout = QVBoxLayout(edit_card)
        edit_layout.setContentsMargins(14, 14, 14, 14)
        edit_layout.setSpacing(9)
        self.edit_title = QLabel("Material / Produto")
        self.edit_title.setProperty("class", "h2")
        edit_layout.addWidget(self.edit_title)
        code_label = QLabel("Código")
        code_label.setProperty("class", "field")
        self.edit_code = QLineEdit()
        self.edit_value_label = QLabel("Descrição")
        self.edit_value_label.setProperty("class", "field")
        self.edit_value = QLineEdit()
        self.save_btn = QPushButton("Salvar Material / Produto")
        self.save_btn.setProperty("class", "primary")
        self.save_btn.clicked.connect(self.save_record)
        edit_layout.addWidget(code_label)
        edit_layout.addWidget(self.edit_code)
        edit_layout.addWidget(self.edit_value_label)
        edit_layout.addWidget(self.edit_value)
        edit_layout.addWidget(self.save_btn)
        cards.addWidget(edit_card)
        body_layout.addLayout(cards)

        table_card = self.card()
        table_card.setMinimumWidth(self.scaled_width(610))
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(14, 14, 14, 14)
        table_layout.setSpacing(10)
        line = QHBoxLayout()
        self.cad_search_layout = line
        self.table_title = QLabel("Materiais / Produtos cadastrados")
        self.table_title.setProperty("class", "h2")
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Buscar por código ou descrição")
        search_btn = QPushButton("Buscar")
        search_btn.clicked.connect(self.search_table)
        line.addWidget(self.table_title, 1)
        line.addWidget(self.search_entry)
        line.addWidget(search_btn)
        table_layout.addLayout(line)
        self.total_label = QLabel("")
        self.total_label.setProperty("class", "muted")
        table_layout.addWidget(self.total_label)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["CÓDIGO", "DESCRIÇÃO", "AÇÕES"])
        self.table.setMinimumHeight(260)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.doubleClicked.connect(self.edit_selected)
        table_layout.addWidget(self.table)
        pager = QHBoxLayout()
        self.per_page_combo = QComboBox()
        self.per_page_combo.addItems(["5", "10", "25", "50"])
        self.per_page_combo.currentTextChanged.connect(self.search_table)
        prev_btn = QPushButton("Anterior")
        prev_btn.clicked.connect(self.prev_page)
        self.page_label = QLabel("")
        next_btn = QPushButton("Próxima")
        next_btn.clicked.connect(self.next_page)
        pager.addStretch()
        pager.addWidget(QLabel("Exibir"))
        pager.addWidget(self.per_page_combo)
        pager.addWidget(prev_btn)
        pager.addWidget(self.page_label)
        pager.addWidget(next_btn)
        table_layout.addLayout(pager)
        body_layout.addWidget(table_card, 1)
        self.cadastro_status = QLabel("")
        self.cadastro_status.setProperty("class", "muted")
        body_layout.addWidget(self.cadastro_status)
        shell_layout.addWidget(body, 1)
        layout.addWidget(shell, 0, Qt.AlignHCenter | Qt.AlignTop)
        return page

    def open_material_selector(self):
        dialog = LookupDialog(
            self,
            "Selecionar Material / Produto",
            "DESCRIÇÃO",
            lambda search, page, per_page: list_materials_paginated(
                self.db_path,
                search=search,
                page=page,
                per_page=per_page,
            ),
        )
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() == QDialog.Accepted and dialog.selected:
            self.entries["codigo"].setText(dialog.selected["code"])
            self.entries["material_desc"].setText(dialog.selected["label"])

    def open_supplier_selector(self):
        dialog = LookupDialog(
            self,
            "Selecionar Fornecedor",
            "NOME",
            lambda search, page, per_page: list_suppliers_paginated(
                self.db_path,
                search=search,
                page=page,
                per_page=per_page,
            ),
        )
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() == QDialog.Accepted and dialog.selected:
            self.entries["fornecedor"].setText(dialog.selected["code"])
            self.entries["fornecedor_nome"].setText(dialog.selected["label"])

    def refresh_counts(self):
        self.counts_label.setText("Carregando cadastros...")
        if hasattr(self, "cad_counts_label"):
            self.cad_counts_label.setText("Carregando cadastros...")
        worker = FunctionWorker(lookup_counts_task, self.db_path)
        worker.signals.finished.connect(self.counts_done)
        worker.signals.failed.connect(self.counts_failed)
        self.counts_worker = worker
        self.thread_pool.start(worker)

    def counts_done(self, counts):
        materials, suppliers = counts
        text = f"{materials} materiais | {suppliers} fornecedores"
        self.counts_label.setText(text)
        if hasattr(self, "cad_counts_label"):
            self.cad_counts_label.setText(text)
        self.counts_worker = None

    def counts_failed(self, _message):
        self.counts_label.setText("Cadastros indisponíveis")
        if hasattr(self, "cad_counts_label"):
            self.cad_counts_label.setText("Cadastros indisponíveis")
        self.counts_worker = None

    def refresh_current_view(self):
        if self.stack.currentWidget() == self.cadastros_page:
            self.refresh_counts()
            self.load_cadastros()
            self.cadastro_status.setText("Cadastros atualizados.")
        else:
            self.lookup_timer.stop()
            self.clear_form()
            self.refresh_counts()

    def lookup_data(self):
        code = normalize_code(self.entries["codigo"].text())
        supplier_code = normalize_code(self.entries["fornecedor"].text())
        self.lookup_request_id += 1
        request_id = self.lookup_request_id
        if not code and not supplier_code:
            self.lookup_worker = None
            return
        worker = FunctionWorker(lookup_form_data_task, self.db_path, code, supplier_code)
        worker.signals.finished.connect(lambda result, rid=request_id: self.lookup_done(rid, result))
        worker.signals.failed.connect(lambda _message, rid=request_id: self.lookup_failed(rid))
        self.lookup_worker = worker
        self.thread_pool.start(worker)

    def lookup_done(self, request_id, result):
        if request_id != self.lookup_request_id:
            return
        if result.get("material_desc") and normalize_code(self.entries["codigo"].text()) == result.get("material_code"):
            self.entries["material_desc"].setText(result["material_desc"])
        if result.get("supplier_name") and normalize_code(self.entries["fornecedor"].text()) == result.get("supplier_code"):
            self.entries["fornecedor_nome"].setText(result["supplier_name"])
        self.lookup_worker = None

    def lookup_failed(self, request_id):
        if request_id == self.lookup_request_id:
            self.lookup_worker = None

    def schedule_lookup_data(self):
        self.lookup_timer.start()

    def sync_pallet_count_from_field(self):
        text = self.entries["pallet"].text().strip()
        if not text:
            count = 1
        else:
            try:
                count = parse_quantity(text, "Pallet")
            except ValueError:
                return
        if count < 1 or count > MAX_LABEL_COPIES:
            return
        if self.copies_spin.value() != count:
            self._syncing_pallet_count = True
            try:
                self.copies_spin.setValue(count)
            finally:
                self._syncing_pallet_count = False

    def sync_pallet_field_from_copy_count(self, count):
        if getattr(self, "_syncing_pallet_count", False):
            return
        pallet_field = self.entries["pallet"]
        text = pallet_field.text().strip()
        if not text:
            return
        try:
            pallet_count = parse_quantity(text, "Pallet")
        except ValueError:
            return
        if not 1 <= pallet_count <= MAX_LABEL_COPIES:
            return
        if text != str(count):
            pallet_field.setText(str(count))

    def sync_total_quantity_from_field(self):
        try:
            quantity = parse_quantity(self.entries["quant"].text(), "Quantidade")
        except ValueError:
            return
        if quantity <= MAX_QUANTITY and self.total_received_spin.value() != quantity:
            self.total_received_spin.setValue(quantity)

    def sync_quantity_field_from_total_spin(self, quantity):
        if not hasattr(self, "entries") or not self.entries.get("quant"):
            return
        try:
            current_quantity = parse_quantity(self.entries["quant"].text(), "Quantidade")
        except ValueError:
            current_quantity = None
        if current_quantity != quantity:
            self.entries["quant"].setText(str(quantity))

    def update_pallet_rows(self):
        if not hasattr(self, "pallets_table"):
            return
        total = self.copies_spin.value()
        self.pallets_box.setVisible(total > 1)
        if total > 1:
            self.sync_total_quantity_from_field()
        target_rows = total if total > 1 else 0
        current_rows = self.pallets_table.rowCount()
        self.pallets_table.blockSignals(True)
        try:
            if current_rows != target_rows:
                self.pallets_table.setRowCount(target_rows)
            for row in range(target_rows):
                pallet_id = f"{row + 1}/{total}"
                pallet_item = self.pallets_table.item(row, 0)
                if pallet_item is None:
                    pallet_item = QTableWidgetItem()
                    pallet_item.setFlags(pallet_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    pallet_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.pallets_table.setItem(row, 0, pallet_item)
                pallet_item.setText(pallet_id)
                qty_item = self.pallets_table.item(row, 1)
                if qty_item is None:
                    qty_item = QTableWidgetItem()
                    qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.pallets_table.setItem(row, 1, qty_item)
            table_height = min(300, max(150, 44 + target_rows * 30))
            self.pallets_table.setMinimumHeight(table_height)
        finally:
            self.pallets_table.blockSignals(False)

    def pallet_quantity_changed(self, item):
        if item.column() != 1:
            return
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def divide_pallet_quantities(self):
        total_pallets = self.copies_spin.value()
        if total_pallets <= 1:
            return
        try:
            total_qty = parse_quantity(self.entries["quant"].text(), "Quantidade total")
        except ValueError as exc:
            QMessageBox.warning(self, "Divisão de quantidades", str(exc))
            return
        if total_qty <= 0:
            QMessageBox.warning(
                self,
                "Divisão de quantidades",
                "Informe uma quantidade total maior que zero.",
            )
            return
        if total_qty > MAX_QUANTITY:
            QMessageBox.warning(
                self,
                "Divisão de quantidades",
                f"A quantidade total não pode exceder {MAX_QUANTITY}.",
            )
            return
        if total_qty < total_pallets:
            QMessageBox.warning(
                self,
                "Divisão de quantidades",
                "A quantidade total deve ter pelo menos uma unidade para cada pallet.",
            )
            return
        if self.total_received_spin.value() != total_qty:
            self.total_received_spin.setValue(total_qty)
        base = total_qty // total_pallets
        remainder = total_qty % total_pallets
        self.pallets_table.blockSignals(True)
        try:
            for row in range(self.pallets_table.rowCount()):
                qty = base + (1 if row < remainder else 0)
                item = self.pallets_table.item(row, 1)
                if item is None:
                    item = QTableWidgetItem()
                    self.pallets_table.setItem(row, 1, item)
                item.setText(str(qty))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        finally:
            self.pallets_table.blockSignals(False)

    def pallet_payloads(self, base_payload, copies):
        if copies <= 1:
            return base_payload
        total_quantity = parse_quantity(base_payload.get("quant"), "Quantidade total")
        if total_quantity <= 0:
            raise ValueError("A quantidade total deve ser maior que zero para dividir entre pallets.")
        if total_quantity > MAX_QUANTITY:
            raise ValueError(f"A quantidade total não pode exceder {MAX_QUANTITY}.")
        if self.pallets_table.rowCount() != copies:
            raise ValueError("A quantidade de linhas de pallets não corresponde ao número de etiquetas.")
        payloads = []
        missing_rows = []
        pallet_total = 0
        for row in range(self.pallets_table.rowCount()):
            pallet_item = self.pallets_table.item(row, 0)
            qty_item = self.pallets_table.item(row, 1)
            pallet_id = pallet_item.text().strip() if pallet_item else f"{row + 1}/{copies}"
            quantity = qty_item.text().strip() if qty_item else ""
            if not quantity:
                missing_rows.append(pallet_id)
                continue
            pallet_quantity = parse_quantity(quantity, f"Quantidade do pallet {pallet_id}")
            if pallet_quantity <= 0:
                raise ValueError(f"O pallet {pallet_id} precisa ter pelo menos uma unidade.")
            pallet_total += pallet_quantity
            payload = dict(base_payload)
            payload["quant"] = str(pallet_quantity)
            payload["pallet"] = pallet_id
            payloads.append(payload)
        if missing_rows:
            raise ValueError("Informe a quantidade dos pallets: " + ", ".join(missing_rows))
        if pallet_total != total_quantity:
            raise ValueError(
                f"A soma das quantidades dos pallets ({pallet_total}) deve ser igual "
                f"à quantidade total informada ({total_quantity})."
            )
        return payloads

    def build_payload(self):
        model = MODELS[self.model_combo.currentText()]
        formats = PRINT_FORMATS.get(self.model_combo.currentText(), {})
        layout_mode = formats.get(self.print_format_combo.currentText(), model["layout_mode"])
        payload = {
            "codigo": self.entries["codigo"].text().strip(),
            "data": self.entries["data"].text().strip(),
            "lote": self.entries["lote"].text().strip(),
            "material": normalize_code(self.entries["codigo"].text()),
            "material_desc": self.entries["material_desc"].text().strip(),
            "insp": self.entries["insp"].text().strip(),
            "ref": self.entries["ref"].text().strip(),
            "dim1": self.entries["dim1"].text().strip(),
            "dim2": self.entries["dim2"].text().strip(),
            "fornecedor": normalize_code(self.entries["fornecedor"].text()),
            "fornecedor_nome": self.entries["fornecedor_nome"].text().strip(),
            "pdc": self.entries["pdc"].text().strip(),
            "quant": self.entries["quant"].text().strip(),
            "nf": self.entries["nf"].text().strip(),
            "os": self.entries["os"].text().strip(),
            "pallet": self.entries["pallet"].text().strip(),
            "label_profile": model["label_profile"],
            "layout_mode": layout_mode,
        }
        copies = self.copies_spin.value()
        pallet_text = payload["pallet"]
        if pallet_text:
            pallet_count = parse_quantity(pallet_text, "Pallet")
            if pallet_count <= 0:
                raise ValueError("A quantidade de pallets deve ser maior que zero.")
            if pallet_count > MAX_LABEL_COPIES:
                raise ValueError(f"O limite é de {MAX_LABEL_COPIES} pallets por geração.")
            if pallet_count != copies:
                raise ValueError(
                    f"O campo Pallet informa {pallet_count}, mas a quantidade de etiquetas "
                    f"está em {copies}. Ajuste um dos valores."
                )
        if payload["quant"]:
            total_quantity = parse_quantity(payload["quant"], "Quantidade")
            if total_quantity > MAX_QUANTITY:
                raise ValueError(f"A quantidade não pode exceder {MAX_QUANTITY}.")
            if copies > 1 and total_quantity <= 0:
                raise ValueError("A quantidade total deve ser maior que zero para dividir entre pallets.")
        elif copies > 1:
            raise ValueError("Informe a quantidade total para dividir entre os pallets.")
        if not payload["material_desc"] and payload["material"]:
            payload["material_desc"] = lookup_material(self.db_path, payload["material"])
        if not payload["fornecedor_nome"] and payload["fornecedor"]:
            payload["fornecedor_nome"] = lookup_supplier(self.db_path, payload["fornecedor"])
        payload = self.pallet_payloads(payload, copies)
        return payload, copies, layout_mode

    def generate_pdf(self):
        try:
            payload, copies, layout_mode = self.build_payload()
        except ValueError as exc:
            QMessageBox.warning(self, "Pallets", str(exc))
            return
        first_payload = payload[0] if isinstance(payload, list) else payload
        if not first_payload["codigo"]:
            QMessageBox.warning(self, "Campo obrigatório", "Informe o código do produto.")
            return
        self.status_label.setText("Gerando PDF...")
        self.generate_btn.setEnabled(False)
        worker = FunctionWorker(generate_pdf_task, self.db_path, self.output_dir, self.logo_path, payload, copies, layout_mode)
        worker.signals.finished.connect(self.pdf_done)
        worker.signals.failed.connect(self.pdf_failed)
        self.thread_pool.start(worker)

    def pdf_done(self, pdf_path):
        self.generate_btn.setEnabled(True)
        if self.last_pdf_path and self.last_pdf_path != pdf_path and self.last_pdf_path.exists():
            try:
                self.last_pdf_path.unlink()
            except Exception:
                pass
        self.last_pdf_path = pdf_path
        self.status_label.setText(f"PDF gerado: {pdf_path.name}")
        self.show_pdf_preview(pdf_path)

    def pdf_failed(self, message):
        self.generate_btn.setEnabled(True)
        self.status_label.setText("")
        QMessageBox.critical(self, "Erro ao gerar PDF", message)

    def open_last_pdf(self):
        if not self.last_pdf_path or not self.last_pdf_path.exists():
            QMessageBox.information(self, "PDF", "Gere uma etiqueta primeiro.")
            return
        self.show_pdf_preview(self.last_pdf_path)

    def show_pdf_preview(self, pdf_path):
        self.load_embedded_preview(Path(pdf_path))

    def load_embedded_preview(self, pdf_path):
        self.last_pdf_path = Path(pdf_path)
        self.preview_filename.setText(self.last_pdf_path.name)
        self.preview_document.close()
        error = self.preview_document.load(str(self.last_pdf_path))
        if error != QPdfDocument.Error.None_:
            QMessageBox.warning(self, "Visualizador", "Não foi possível carregar o PDF.")
            return
        try:
            self.preview_viewer.setPageMode(QPdfView.PageMode.MultiPage)
            self.preview_viewer.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        except Exception:
            pass
        self.preview_zoom_label.setText("Ajustado")
        self.preview_card.show()
        self.preview_card.setFocus()

    def zoom_preview(self, factor):
        if not self.last_pdf_path:
            return
        try:
            current = self.preview_viewer.zoomFactor()
            zoom = max(0.25, min(4.0, current * factor))
            self.preview_viewer.setZoomMode(QPdfView.ZoomMode.Custom)
            self.preview_viewer.setZoomFactor(zoom)
            self.preview_zoom_label.setText(f"{int(zoom * 100)}%")
        except Exception:
            pass

    def fit_preview_width(self):
        try:
            self.preview_viewer.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.preview_zoom_label.setText("Ajustado")
        except Exception:
            pass

    def print_preview_pdf(self):
        if not self.last_pdf_path:
            return
        try:
            print_pdf(self.last_pdf_path)
        except Exception as exc:
            QMessageBox.warning(self, "Imprimir", f"Não foi possível enviar para impressão.\n\n{exc}")

    def save_preview_pdf(self):
        if not self.last_pdf_path:
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar etiqueta",
            str(APP_ROOT / self.last_pdf_path.name),
            "PDF (*.pdf)",
        )
        if not target:
            return
        target_path = Path(target)
        if target_path.suffix.lower() != ".pdf":
            target_path = target_path.with_suffix(".pdf")
        try:
            shutil.copy2(self.last_pdf_path, target_path)
        except Exception as exc:
            QMessageBox.warning(self, "Salvar como", f"Não foi possível salvar o PDF.\n\n{exc}")
            return
        QMessageBox.information(self, "Salvar como", "PDF salvo.")

    def open_preview_external(self):
        if self.last_pdf_path:
            open_file(self.last_pdf_path)

    def close_preview(self):
        self.preview_card.hide()
        self.preview_document.close()

    def clear_form(self):
        for key, entry in self.entries.items():
            entry.clear()
        self.model_combo.setCurrentText("Matéria-Prima")
        self.update_print_formats("Matéria-Prima")
        self.entries["data"].setText(datetime.now().strftime("%d/%m/%y"))
        self.entries["ref"].setText("0,00")
        self.entries["dim1"].setText("1200")
        self.entries["dim2"].setText("2000")
        self.copies_spin.setValue(1)
        if hasattr(self, "total_received_spin"):
            self.total_received_spin.setValue(0)
        self.update_pallet_rows()
        if hasattr(self, "preview_card"):
            self.close_preview()
        self.status_label.clear()

    def set_cadastro_section(self, section, load=True):
        self.cadastro_section = section
        self.cadastro_page = 1
        is_materials = section == "materials"
        self.materials_btn.setProperty("class", "tabActive" if is_materials else "tabInactive")
        self.suppliers_btn.setProperty("class", "tabInactive" if is_materials else "tabActive")
        self.repolish(self.materials_btn)
        self.repolish(self.suppliers_btn)
        self.edit_title.setText("Material / Produto" if is_materials else "Fornecedor")
        self.edit_value_label.setText("Descrição" if is_materials else "Nome")
        self.save_btn.setText("Salvar Material / Produto" if is_materials else "Salvar Fornecedor")
        self.table_title.setText("Materiais / Produtos cadastrados" if is_materials else "Fornecedores cadastrados")
        self.table.setHorizontalHeaderLabels(["CÓDIGO", "DESCRIÇÃO" if is_materials else "NOME", "AÇÕES"])
        self.repolish(self.table)
        if load:
            self.load_cadastros()

    def load_cadastros(self):
        per_page = int(self.per_page_combo.currentText()) if hasattr(self, "per_page_combo") else 5
        search = self.search_entry.text().strip() if hasattr(self, "search_entry") else ""
        self.cadastros_request_id += 1
        request_id = self.cadastros_request_id
        self.total_label.setText("Carregando...")
        self.page_label.setText("")
        worker = FunctionWorker(
            load_lookup_page_task,
            self.db_path,
            self.cadastro_section,
            search,
            self.cadastro_page,
            per_page,
        )
        worker.signals.finished.connect(lambda data, rid=request_id: self.cadastros_done(rid, data))
        worker.signals.failed.connect(lambda message, rid=request_id: self.cadastros_failed(rid, message))
        self.cadastros_worker = worker
        self.thread_pool.start(worker)

    def cadastros_done(self, request_id, data):
        if request_id != self.cadastros_request_id:
            return
        self.cadastro_pages = data["pages"]
        self.table.setRowCount(0)
        for item in data["items"]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item["code"]))
            self.table.setItem(row, 1, QTableWidgetItem(item["label"]))
            self.table.setItem(row, 2, QTableWidgetItem("duplo clique"))
        self.total_label.setText(f"Total: {data['total']}")
        self.page_label.setText(f"Página {data['page']} de {data['pages']}")
        self.cadastros_worker = None

    def cadastros_failed(self, request_id, message):
        if request_id != self.cadastros_request_id:
            return
        self.total_label.setText("Não foi possível carregar os cadastros.")
        self.page_label.setText("")
        self.cadastro_status.setText(message)
        self.cadastros_worker = None

    def search_table(self):
        self.cadastro_page = 1
        self.load_cadastros()

    def prev_page(self):
        if self.cadastro_page > 1:
            self.cadastro_page -= 1
            self.load_cadastros()

    def next_page(self):
        if self.cadastro_page < self.cadastro_pages:
            self.cadastro_page += 1
            self.load_cadastros()

    def edit_selected(self, _index=None):
        row = self.table.currentRow()
        if row < 0:
            return
        self.edit_code.setText(self.table.item(row, 0).text())
        self.edit_value.setText(self.table.item(row, 1).text())

    def save_record(self):
        code = self.edit_code.text().strip()
        value = self.edit_value.text().strip()
        if self.cadastro_section == "materials":
            ok = upsert_material(self.db_path, code, value)
            msg = "Material / Produto salvo."
        else:
            ok = upsert_supplier(self.db_path, code, value)
            msg = "Fornecedor salvo."
        if not ok:
            QMessageBox.warning(self, "Cadastro", "Informe código e valor.")
            return
        self.cadastro_status.setText(msg)
        QMessageBox.information(self, "Cadastro", msg)
        self.edit_code.clear()
        self.edit_value.clear()
        self.refresh_counts()
        self.load_cadastros()

    def import_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Importar tabela",
            str(APP_DATA_DIR),
            "Planilhas (*.csv *.ods *.xlsx *.xlsm);;CSV (*.csv);;LibreOffice Calc (*.ods);;Excel (*.xlsx *.xlsm)",
        )
        if not filename:
            return
        selected = Path(filename)
        self.import_file_label.setText(f"Arquivo selecionado: {selected.name}")
        self.import_file_label.setToolTip(str(selected))
        self.import_result_label.setText("Importando dados...")
        self.cadastro_status.setText(f"Importando: {selected.name}")
        self.import_btn.setEnabled(False)
        worker = FunctionWorker(import_lookup_file, self.db_path, filename)
        worker.signals.finished.connect(self.import_done)
        worker.signals.failed.connect(self.import_failed)
        self.thread_pool.start(worker)

    def import_done(self, message):
        self.import_btn.setEnabled(True)
        self.import_result_label.setText(message)
        self.cadastro_status.setText(message)
        self.refresh_counts()
        self.load_cadastros()

    def import_failed(self, message):
        self.import_btn.setEnabled(True)
        self.import_result_label.setText("Falha na importação.")
        self.cadastro_status.setText("Falha na importação.")
        QMessageBox.critical(self, "Importar tabela", message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon_path = app_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = AlmoxarifadoWindow()
    window.show()
    sys.exit(app.exec())
