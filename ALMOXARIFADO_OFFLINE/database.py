import csv
import hashlib
import io
import sqlite3
import unicodedata
from pathlib import Path


def normalize_code(value):
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()

    text = str(value).strip()
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except ValueError:
            return text
    return text


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS materials (
            code TEXT PRIMARY KEY,
            description TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS suppliers (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )

    cur.execute("DROP TABLE IF EXISTS labels_history")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_materials_description ON materials (description)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers (name)")

    conn.commit()
    conn.close()


def seed_lookup_data(db_path: Path, seed_path: Path):
    if not seed_path.is_file():
        return False

    seed_hash = hashlib.sha256(seed_path.read_bytes()).hexdigest()
    conn = sqlite3.connect(db_path)
    attached = False
    try:
        conn.execute("ATTACH DATABASE ? AS lookup_seed", (str(seed_path),))
        attached = True
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        row = conn.execute(
            "SELECT value FROM app_metadata WHERE key = ?",
            ("lookup_seed_sha256",),
        ).fetchone()
        if row and row[0] == seed_hash:
            return False

        conn.execute(
            """
            INSERT OR IGNORE INTO materials (code, description)
            SELECT code, description FROM lookup_seed.materials
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO suppliers (code, name)
            SELECT code, name FROM lookup_seed.suppliers
            """
        )
        conn.execute(
            """
            INSERT INTO app_metadata (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("lookup_seed_sha256", seed_hash),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        if attached:
            conn.execute("DETACH DATABASE lookup_seed")
        conn.close()


def _read_sheet_map(doc, sheet_name: str):
    table = {}
    if sheet_name not in doc.sheets.names():
        return table

    sheet = doc.sheets[sheet_name]
    for row in range(sheet.nrows()):
        key = normalize_code(sheet[row, 0].value)
        value = sheet[row, 1].value
        if not key or value is None:
            continue

        text = str(value).strip()
        if text:
            table[key] = text

    return table


def _read_ods_lookups(template_path: Path):
    """Reads Material/Fornecedor sheets from ODS.

    This is optional. If ezodf/lxml is not installed, it returns empty maps
    and the app still works with manual input.
    """
    try:
        import ezodf
    except Exception:
        return {}, {}

    try:
        doc = ezodf.opendoc(str(template_path))
    except Exception:
        return {}, {}

    materials = _read_sheet_map(doc, "Material")
    suppliers = _read_sheet_map(doc, "Fornecedor")
    return materials, suppliers


def import_lookups_if_empty(db_path: Path, template_path: Path):
    if not template_path.exists():
        return False

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM materials")
    material_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM suppliers")
    supplier_count = cur.fetchone()[0]

    needs_materials = material_count == 0
    needs_suppliers = supplier_count == 0

    if not needs_materials and not needs_suppliers:
        conn.close()
        return False

    materials, suppliers = _read_ods_lookups(template_path)
    inserted = False

    if needs_materials and materials:
        cur.executemany(
            "INSERT OR REPLACE INTO materials (code, description) VALUES (?, ?)",
            list(materials.items()),
        )
        inserted = True

    if needs_suppliers and suppliers:
        cur.executemany(
            "INSERT OR REPLACE INTO suppliers (code, name) VALUES (?, ?)",
            list(suppliers.items()),
        )
        inserted = True

    conn.commit()
    conn.close()
    return inserted


def get_lookup_counts(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM materials")
    material_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM suppliers")
    supplier_count = cur.fetchone()[0]

    conn.close()
    return material_count, supplier_count


def lookup_material(db_path: Path, code: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT description FROM materials WHERE code = ?", (normalize_code(code),))
    row = cur.fetchone()

    conn.close()
    return row[0] if row else ""


def lookup_supplier(db_path: Path, code: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT name FROM suppliers WHERE code = ?", (normalize_code(code),))
    row = cur.fetchone()

    conn.close()
    return row[0] if row else ""


def list_materials(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT code, description FROM materials ORDER BY code")
    rows = cur.fetchall()
    conn.close()
    return rows


def list_suppliers(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT code, name FROM suppliers ORDER BY code")
    rows = cur.fetchall()
    conn.close()
    return rows


def _normalize_search(value):
    return str(value or "").strip()


def _clamp_page(page, default=1):
    try:
        parsed = int(str(page).strip())
    except Exception:
        parsed = default
    return max(1, parsed)


def _clamp_per_page(per_page, default=25, maximum=100):
    try:
        parsed = int(str(per_page).strip())
    except Exception:
        parsed = default
    return max(1, min(maximum, parsed))


def _list_lookup_table(db_path: Path, *, table: str, text_column: str, search: str = "", page=1, per_page=25):
    search = _normalize_search(search)
    page = _clamp_page(page)
    per_page = _clamp_per_page(per_page)
    offset = (page - 1) * per_page

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    where_sql = ""
    params = []
    if search:
        like_value = f"%{search}%"
        where_sql = f"WHERE code LIKE ? OR {text_column} LIKE ?"
        params = [like_value, like_value]

    cur.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT code, {text_column}
        FROM {table}
        {where_sql}
        ORDER BY code
        LIMIT ? OFFSET ?
        """,
        [*params, per_page, offset],
    )
    rows = cur.fetchall()
    conn.close()

    items = [{"code": row[0], "label": row[1]} for row in rows]
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "search": search,
    }


def list_materials_paginated(db_path: Path, search: str = "", page=1, per_page=25):
    return _list_lookup_table(
        db_path,
        table="materials",
        text_column="description",
        search=search,
        page=page,
        per_page=per_page,
    )


def list_suppliers_paginated(db_path: Path, search: str = "", page=1, per_page=25):
    return _list_lookup_table(
        db_path,
        table="suppliers",
        text_column="name",
        search=search,
        page=page,
        per_page=per_page,
    )


def upsert_material(db_path: Path, code: str, description: str):
    code = normalize_code(code)
    description = str(description or "").strip()
    if not code or not description:
        return False

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO materials (code, description) VALUES (?, ?)",
        (code, description),
    )
    conn.commit()
    conn.close()
    return True


def upsert_supplier(db_path: Path, code: str, name: str):
    code = normalize_code(code)
    name = str(name or "").strip()
    if not code or not name:
        return False

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO suppliers (code, name) VALUES (?, ?)",
        (code, name),
    )
    conn.commit()
    conn.close()
    return True


def _normalize_header(value):
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace(" ", "_").replace("-", "_")
    return text


def _decode_csv_bytes(file_bytes: bytes):
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def _parse_csv_rows(file_bytes: bytes):
    text = _decode_csv_bytes(file_bytes)
    stream = io.StringIO(text)
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        return None, []

    normalized_map = {}
    for header in reader.fieldnames:
        normalized_map[_normalize_header(header)] = header

    rows = list(reader)
    return normalized_map, rows


def _extract_csv_value(row: dict, field_map: dict, aliases):
    for alias in aliases:
        header = field_map.get(_normalize_header(alias))
        if header is None:
            continue
        value = row.get(header)
        if value is not None:
            return str(value).strip()
    return ""


def _import_lookup_csv(db_path: Path, *, file_bytes: bytes, code_aliases, value_aliases, table: str, value_column: str):
    field_map, rows = _parse_csv_rows(file_bytes)
    if field_map is None:
        return {"ok": False, "message": "O arquivo CSV precisa ter cabeçalho."}

    has_code = any(_normalize_header(alias) in field_map for alias in code_aliases)
    has_value = any(_normalize_header(alias) in field_map for alias in value_aliases)
    if not has_code or not has_value:
        return {"ok": False, "message": "Cabeçalho inválido para o tipo de importação."}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    created = 0
    updated = 0
    ignored = 0

    try:
        for row in rows:
            code = normalize_code(_extract_csv_value(row, field_map, code_aliases))
            value = _extract_csv_value(row, field_map, value_aliases)

            if not code and not value:
                continue

            if not code or not value:
                ignored += 1
                continue

            cur.execute(f"SELECT 1 FROM {table} WHERE code = ?", (code,))
            exists = cur.fetchone() is not None

            if exists:
                cur.execute(
                    f"UPDATE {table} SET {value_column} = ? WHERE code = ?",
                    (value, code),
                )
                updated += 1
            else:
                cur.execute(
                    f"INSERT INTO {table} (code, {value_column}) VALUES (?, ?)",
                    (code, value),
                )
                created += 1

        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return {"ok": False, "message": "Não foi possível concluir a importação."}

    conn.close()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "ignored": ignored,
        "message": f"Importação concluída: {created} novos, {updated} atualizados e {ignored} ignorados.",
    }


def import_materials_csv(db_path: Path, file_bytes: bytes):
    return _import_lookup_csv(
        db_path,
        file_bytes=file_bytes,
        code_aliases=["codigo", "código", "cod"],
        value_aliases=["descricao", "descrição", "description", "produto", "material"],
        table="materials",
        value_column="description",
    )


def import_suppliers_csv(db_path: Path, file_bytes: bytes):
    return _import_lookup_csv(
        db_path,
        file_bytes=file_bytes,
        code_aliases=["codigo", "código", "cod"],
        value_aliases=["nome", "fornecedor", "razao_social"],
        table="suppliers",
        value_column="name",
    )
