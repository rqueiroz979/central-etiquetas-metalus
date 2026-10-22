import json
import os
import shutil
import sys
from io import BytesIO
from datetime import datetime
from functools import lru_cache, wraps
from pathlib import Path
from threading import Timer
import webbrowser

from flask import Flask, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for

from backup_manager import (
    create_backup,
    ensure_backup_dir,
    get_backup_file_path as get_managed_backup_file_path,
    list_backups,
    restore_backup,
)
from database import (
    get_latest_label_snapshot,
    get_lookup_counts,
    import_materials_csv,
    import_suppliers_csv,
    import_lookups_if_empty,
    init_db,
    list_materials,
    list_materials_paginated,
    list_suppliers,
    list_suppliers_paginated,
    lookup_material,
    lookup_supplier,
    normalize_code,
    save_history,
    upsert_material,
    upsert_supplier,
)
from ods_import import SUPPORTED_IDENTIFICACAO_EXTENSIONS, parse_identificacao_spreadsheet
from pdf_label import generate_identificacao_batch_pdf, generate_identificacao_pdf, generate_label_pdf


RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if getattr(sys, "frozen", False):
    if os.name == "nt":
        USER_DATA_ROOT = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        USER_DATA_ROOT = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    APP_ROOT = USER_DATA_ROOT / "CentralEtiquetasMetalus"
else:
    APP_ROOT = Path(__file__).resolve().parent

APP_ROOT.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = APP_ROOT / "config.json"
DEFAULT_CONFIG_PATH = RESOURCE_ROOT / "config.json"
DEFAULT_DB_PATH = APP_ROOT / "data" / "etiquetas.db"
DEFAULT_OUTPUT_DIR = APP_ROOT / "output"
DEFAULT_BACKUP_DIR = APP_ROOT / "backups"
DEFAULT_ADMIN_PASSWORD = "Metalus@admin"


app = Flask(
    __name__,
    template_folder=str(RESOURCE_ROOT / "templates"),
    static_folder=str(RESOURCE_ROOT / "static"),
)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.jinja_env.auto_reload = True


def load_config():
    if not CONFIG_PATH.exists():
        if not DEFAULT_CONFIG_PATH.exists():
            return {}
        shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _to_path(value, fallback: Path):
    text = str(value or "").strip()
    return Path(text) if text else fallback


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _absolute_from_app(path: Path) -> Path:
    return path if path.is_absolute() else (APP_ROOT / path)


def _template_path(config) -> Path:
    configured = _to_path(
        config.get("template_path"),
        RESOURCE_ROOT / "Etiquetas Identificação de Matéria Prima.ods",
    )
    if configured.is_absolute():
        return configured

    user_path = APP_ROOT / configured
    if user_path.exists():
        return user_path
    bundled_template = RESOURCE_ROOT / "template.ods"
    if bundled_template.exists():
        return bundled_template
    return RESOURCE_ROOT / configured


def _clean(value):
    return str(value or "").strip()


def _asset_version(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except Exception:
        return 1


def _static_asset_context(filename: str):
    path = RESOURCE_ROOT / "static" / filename
    if not path.exists():
        return None, None
    return filename, _asset_version(path)


def _as_bool(value, default=False):
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on", "sim"}


def _as_int(value, default=1, minimum=1, maximum=30):
    try:
        number = int(str(value).strip())
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


def get_admin_password(config):
    return _clean(os.getenv("ETIQUETA_ADMIN_PASSWORD") or config.get("admin_password") or DEFAULT_ADMIN_PASSWORD)


def is_debug_enabled(config):
    if "FLASK_DEBUG" in os.environ:
        return _as_bool(os.getenv("FLASK_DEBUG"))
    return _as_bool(config.get("flask_debug"), default=False)


@app.context_processor
def inject_asset_versions():
    return {
        "style_version": _asset_version(RESOURCE_ROOT / "static" / "style.css"),
    }


@app.after_request
def add_no_cache_headers(response):
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@lru_cache(maxsize=1)
def bootstrap_database_cached(db_path_str: str, template_path_str: str, template_mtime_ns: int):
    db_path = Path(db_path_str)
    init_db(db_path)

    template_path = Path(template_path_str)
    if template_mtime_ns > 0 and template_path.exists():
        import_lookups_if_empty(db_path, template_path)

    return db_path_str


def get_db_path(config):
    db_path = _absolute_from_app(_to_path(config.get("db_path"), DEFAULT_DB_PATH))
    template_path = _template_path(config)

    template_mtime_ns = -1
    if template_path.exists():
        template_mtime_ns = template_path.stat().st_mtime_ns

    bootstrap_database_cached(str(db_path), str(template_path), template_mtime_ns)
    return db_path


def get_output_dir(config):
    output_dir = _absolute_from_app(_to_path(config.get("output_dir"), DEFAULT_OUTPUT_DIR))
    return ensure_output_dir(output_dir)


def get_latest_generated_pdf(output_dir: Path, pattern: str) -> str | None:
    files = [item for item in output_dir.glob(pattern) if item.is_file()]
    if not files:
        return None
    latest = max(files, key=lambda item: item.stat().st_mtime)
    return latest.name


def get_backup_dir() -> Path:
    return ensure_backup_dir(DEFAULT_BACKUP_DIR)


def get_absolute_db_path(config) -> Path:
    return _absolute_from_app(get_db_path(config))


def get_absolute_output_dir(config) -> Path:
    output_dir = _absolute_from_app(_to_path(config.get("output_dir"), DEFAULT_OUTPUT_DIR))
    return ensure_output_dir(output_dir)


def require_admin(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"ok": False, "message": "Acesso restrito. Informe a senha."}), 403
        return view_func(*args, **kwargs)

    return wrapped


def require_admin_page(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_page"))
        return view_func(*args, **kwargs)

    return wrapped



def build_payload(form_data, db_path: Path):
    label_profile = _clean(form_data.get("label_profile"))
    if label_profile not in {"materia_prima", "usinados", "bens_consumo"}:
        label_profile = "materia_prima"

    payload = {
        "codigo": _clean(form_data.get("codigo")),
        "data": _clean(form_data.get("data")),
        "lote": _clean(form_data.get("lote")),
        # O c\u00f3digo do produto \u00e9 o c\u00f3digo base para buscar a descri\u00e7\u00e3o do material.
        "material": normalize_code(form_data.get("codigo")),
        "material_desc": _clean(form_data.get("material_desc")),
        "insp": _clean(form_data.get("insp")),
        "ref": _clean(form_data.get("ref")),
        "dim1": _clean(form_data.get("dim1")),
        "dim2": _clean(form_data.get("dim2")),
        "fornecedor": normalize_code(form_data.get("fornecedor")),
        "fornecedor_nome": _clean(form_data.get("fornecedor_nome")),
        "pdc": _clean(form_data.get("pdc")),
        "quant": _clean(form_data.get("quant")),
        "nf": _clean(form_data.get("nf")),
        "os": _clean(form_data.get("os")),
        "pallet": _clean(form_data.get("pallet")),
        "label_profile": label_profile,
    }

    if not payload["material_desc"] and payload["material"]:
        payload["material_desc"] = lookup_material(db_path, payload["material"])

    if not payload["fornecedor_nome"] and payload["fornecedor"]:
        payload["fornecedor_nome"] = lookup_supplier(db_path, payload["fornecedor"])

    copies = _as_int(form_data.get("copies"), default=1, minimum=1, maximum=300)
    layout_mode = _clean(form_data.get("layout_mode"))
    if layout_mode == "a4_6":
        # Backward compatibility for older UI option.
        layout_mode = "a4_12"
    if layout_mode not in {"a4_12", "label_100x70", "label_140x70"}:
        layout_mode = "a4_12"

    return payload, copies, layout_mode


def generate_pdf_from_form(form_data):
    config = load_config()
    db_path = get_db_path(config)
    output_dir = get_output_dir(config)

    payload, copies, layout_mode = build_payload(form_data, db_path)
    logo_path = RESOURCE_ROOT / "static" / "logo-metalus.png"
    payload["layout_mode"] = layout_mode

    pdf_path = generate_label_pdf(
        output_dir=output_dir,
        logo_path=logo_path,
        payload=payload,
        copies=copies,
        layout_mode=layout_mode,
    )

    payload["created_at"] = datetime.now().isoformat(timespec="seconds")
    save_history(db_path, payload)

    return pdf_path


def build_identificacao_payload(form_data):
    return {
        "os": _clean(form_data.get("os")),
        "data": _clean(form_data.get("data")) or datetime.now().strftime("%d/%m/%Y"),
        "codigo_item": _clean(form_data.get("codigo_item")),
        "quantidade_lote": _clean(form_data.get("quantidade_lote")),
        "quantidade_nc": _clean(form_data.get("quantidade_nc")),
        "inspetor": _clean(form_data.get("inspetor")),
        "nao_conformidade": _clean(form_data.get("nao_conformidade")),
    }


def generate_identificacao_from_form(form_data):
    config = load_config()
    output_dir = get_output_dir(config)
    logo_path = RESOURCE_ROOT / "static" / "logo-metalus.png"
    payload = build_identificacao_payload(form_data)
    return generate_identificacao_pdf(output_dir=output_dir, logo_path=logo_path, payload=payload)


def build_identificacao_batch_payload(rows):
    today = datetime.now().strftime("%d/%m/%Y")
    payloads = []
    for row in rows or []:
        payloads.append(
            {
                "os": _clean(row.get("os")),
                "data": _clean(row.get("data")) or today,
                "codigo_item": _clean(row.get("codigo_item")),
                "quantidade_lote": _clean(row.get("quantidade_lote")),
                "quantidade_nc": _clean(row.get("quantidade_nc")),
                "inspetor": _clean(row.get("inspetor")),
                "nao_conformidade": _clean(row.get("nao_conformidade")),
            }
        )
    return payloads


def generate_identificacao_batch(rows):
    config = load_config()
    output_dir = get_output_dir(config)
    logo_path = RESOURCE_ROOT / "static" / "logo-metalus.png"
    payloads = build_identificacao_batch_payload(rows)
    return generate_identificacao_batch_pdf(output_dir=output_dir, logo_path=logo_path, payloads=payloads)


config_for_secret = load_config()
app.secret_key = _clean(os.getenv("FLASK_SECRET_KEY") or config_for_secret.get("flask_secret_key") or "change-me-metalus")


@app.get("/")
def home():
    config = load_config()
    db_path = get_db_path(config)
    material_count, fornecedor_count = get_lookup_counts(db_path)
    logo_path = RESOURCE_ROOT / "static" / "logo-metalus.png"
    logo_version = int(logo_path.stat().st_mtime) if logo_path.exists() else 1
    materia_prima_card_image, materia_prima_card_image_version = _static_asset_context("materia-prima-card.png")
    usinados_card_image, usinados_card_image_version = _static_asset_context("usinados-card.png")
    identificacao_card_image, identificacao_card_image_version = _static_asset_context("identificacao-card.png")
    if not identificacao_card_image:
        identificacao_card_image, identificacao_card_image_version = _static_asset_context("identificação-card.png")
    latest_usinados_snapshot = get_latest_label_snapshot(db_path, layout_mode="label_140x70")

    return render_template(
        "home.html",
        material_count=material_count,
        fornecedor_count=fornecedor_count,
        admin_unlocked=bool(session.get("is_admin")),
        logo_version=logo_version,
        materia_prima_card_image=materia_prima_card_image,
        materia_prima_card_image_version=materia_prima_card_image_version,
        usinados_card_image=usinados_card_image,
        usinados_card_image_version=usinados_card_image_version,
        identificacao_card_image=identificacao_card_image,
        identificacao_card_image_version=identificacao_card_image_version,
        latest_usinados_snapshot=latest_usinados_snapshot,
    )


ADMIN_SECTIONS = {
    "configuracoes": {
        "key": "configuracoes",
        "title": "Configurações",
        "headline": "Backup, restauração e controle do sistema",
        "description": "Área protegida para tarefas sensíveis do sistema.",
        "eyebrow": "Painel Protegido",
        "section_title": "Configurações",
        "section_description": "Backup geral, restauração e controle administrativo.",
        "stats_material_label": "Materiais cadastrados",
        "stats_supplier_label": "Fornecedores cadastrados",
        "show_forms": False,
    },
    "cadastros": {
        "key": "cadastros",
        "title": "Cadastros",
        "headline": "Cadastro de materiais, produtos e fornecedores",
        "description": "Gerencie os dados usados no preenchimento automático das etiquetas.",
        "eyebrow": "Base Operacional",
        "section_title": "Cadastros",
        "section_description": "Materiais, produtos e fornecedores centralizados em uma única área.",
        "stats_material_label": "Materiais / produtos cadastrados",
        "stats_supplier_label": "Fornecedores cadastrados",
        "show_forms": True,
    },
    "identificacao": {
        "key": "identificacao",
        "title": "Etiqueta de Identificação",
        "headline": "Cadastros da etiqueta de identificação",
        "description": "Esta subtela fica reservada para os dados auxiliares da etiqueta de identificação quando as regras de negócio forem concluídas.",
        "eyebrow": "Subtela Ativa",
        "section_title": "Etiqueta de Identificação",
        "section_description": "Estrutura preparada para receber campos, validações e listas específicas deste modelo.",
        "stats_material_label": "Estruturas planejadas",
        "stats_supplier_label": "Integrações previstas",
        "show_forms": False,
    },
    "proximas-etiquetas": {
        "key": "proximas-etiquetas",
        "title": "Próximas Etiquetas",
        "headline": "Expansão para novos modelos",
        "description": "Use esta subtela como base para futuras etiquetas que precisarem de parâmetros, listas auxiliares e cadastros dedicados.",
        "eyebrow": "Subtela Ativa",
        "section_title": "Novos modelos de etiqueta",
        "section_description": "Cada nova etiqueta poderá ganhar sua própria área administrativa sem misturar regras e cadastros.",
        "stats_material_label": "Modelos futuros",
        "stats_supplier_label": "Cadastros dedicados",
        "show_forms": False,
    },
}


@app.get("/admin")
def admin_page():
    return admin_section("configuracoes")


@app.get("/admin/backup")
@require_admin_page
def admin_backup_page():
    return redirect(url_for("admin_section", section="configuracoes", _anchor="backup-tools"))


@app.get("/admin/<section>")
def admin_section(section):
    active_section = ADMIN_SECTIONS.get(section)
    if not active_section:
        return ("Subtela administrativa não encontrada.", 404)

    config = load_config()
    db_path = get_db_path(config)
    material_count, fornecedor_count = get_lookup_counts(db_path)
    logo_path = RESOURCE_ROOT / "static" / "logo-metalus.png"
    logo_version = int(logo_path.stat().st_mtime) if logo_path.exists() else 1

    return render_template(
        "admin.html",
        material_count=material_count,
        fornecedor_count=fornecedor_count,
        admin_unlocked=bool(session.get("is_admin")),
        logo_version=logo_version,
        admin_sections=ADMIN_SECTIONS.values(),
        active_section=active_section,
        backup_files=list_backups(get_backup_dir()) if session.get("is_admin") else [],
    )


@app.get("/materia-prima")
def materia_prima():
    config = load_config()
    db_path = get_db_path(config)
    material_count, fornecedor_count = get_lookup_counts(db_path)
    materials = list_materials(db_path)
    suppliers = list_suppliers(db_path)
    default_layout_mode = _clean(request.args.get("layout_mode"))
    if default_layout_mode not in {"a4_12", "label_100x70", "label_140x70"}:
        default_layout_mode = "a4_12"
    default_label_profile = _clean(request.args.get("label_profile"))
    if default_label_profile not in {"materia_prima", "usinados", "bens_consumo"}:
        default_label_profile = "materia_prima"

    logo_path = RESOURCE_ROOT / "static" / "logo-metalus.png"
    logo_version = int(logo_path.stat().st_mtime) if logo_path.exists() else 1

    return render_template(
        "index.html",
        material_count=material_count,
        fornecedor_count=fornecedor_count,
        materials=materials,
        suppliers=suppliers,
        logo_version=logo_version,
        default_data=datetime.now().strftime("%d/%m/%y"),
        default_layout_mode=default_layout_mode,
        default_label_profile=default_label_profile,
        admin_unlocked=bool(session.get("is_admin")),
    )


@app.get("/identificacao")
def identificacao():
    logo_path = RESOURCE_ROOT / "static" / "logo-metalus.png"
    logo_version = int(logo_path.stat().st_mtime) if logo_path.exists() else 1
    return render_template("identificacao.html", logo_version=logo_version, default_data=datetime.now().strftime("%d/%m/%Y"))


@app.post("/identificacao/importar_ods")
@app.post("/identificacao/importar_planilha")
def importar_planilha_identificacao():
    upload = request.files.get("arquivo_planilha") or request.files.get("arquivo_ods")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "message": "Selecione uma planilha .ods, .xlsx ou .xlsm."}), 400

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in SUPPORTED_IDENTIFICACAO_EXTENSIONS:
        return jsonify({"ok": False, "message": "Envie uma planilha .ods, .xlsx ou .xlsm."}), 400

    try:
        rows = parse_identificacao_spreadsheet(upload.read(), upload.filename)
    except Exception:
        return jsonify({"ok": False, "message": "N\u00e3o foi poss\u00edvel ler a planilha enviada."}), 400

    if not rows:
        return jsonify({"ok": False, "message": "Nenhum registro com OS, Pe\u00e7a e Qtde foi encontrado."}), 404

    return jsonify({"ok": True, "rows": rows, "count": len(rows)})


@app.post("/identificacao/gerar_preview")
def gerar_preview_identificacao():
    pdf_path = generate_identificacao_from_form(request.form)
    preview_url = url_for("arquivo_pdf", filename=pdf_path.name)
    download_url = url_for("arquivo_pdf", filename=pdf_path.name, download=1)
    return jsonify(
        {
            "ok": True,
            "preview_url": preview_url,
            "download_url": download_url,
            "filename": pdf_path.name,
        }
    )


@app.post("/identificacao/gerar_lote_preview")
def gerar_lote_preview_identificacao():
    data = request.get_json(silent=True) or {}
    rows = data.get("rows") or []
    if not rows:
        return jsonify({"ok": False, "message": "Selecione ao menos um registro para gerar em lote."}), 400

    pdf_path = generate_identificacao_batch(rows)
    preview_url = url_for("arquivo_pdf", filename=pdf_path.name)
    download_url = url_for("arquivo_pdf", filename=pdf_path.name, download=1)
    return jsonify(
        {
            "ok": True,
            "preview_url": preview_url,
            "download_url": download_url,
            "filename": pdf_path.name,
        }
    )


@app.get("/lookup")
def lookup():
    config = load_config()
    db_path = get_db_path(config)

    material_code = normalize_code(request.args.get("material_code", ""))
    fornecedor_code = normalize_code(request.args.get("fornecedor_code", ""))

    material_desc = lookup_material(db_path, material_code)
    fornecedor_nome = lookup_supplier(db_path, fornecedor_code)

    return jsonify(
        {
            "material_code": material_code,
            "material_desc": material_desc,
            "material_found": bool(material_desc),
            "fornecedor_code": fornecedor_code,
            "fornecedor_nome": fornecedor_nome,
            "fornecedor_found": bool(fornecedor_nome),
        }
    )


@app.post("/gerar")
def gerar_download():
    pdf_path = generate_pdf_from_form(request.form)
    return send_file(pdf_path, as_attachment=True, download_name=pdf_path.name)


@app.post("/gerar_preview")
def gerar_preview():
    pdf_path = generate_pdf_from_form(request.form)
    preview_url = url_for("arquivo_pdf", filename=pdf_path.name)
    download_url = url_for("arquivo_pdf", filename=pdf_path.name, download=1)

    return jsonify(
        {
            "ok": True,
            "preview_url": preview_url,
            "download_url": download_url,
            "filename": pdf_path.name,
        }
    )


@app.get("/arquivo/<path:filename>")
def arquivo_pdf(filename):
    config = load_config()
    output_dir = get_output_dir(config)
    download = request.args.get("download") == "1"

    return send_from_directory(
        output_dir,
        filename,
        as_attachment=download,
        download_name=filename,
        mimetype="application/pdf",
    )


@app.get("/admin/status")
def admin_status():
    return jsonify({"unlocked": bool(session.get("is_admin"))})


@app.post("/admin/backup/create")
@require_admin
def admin_backup_create():
    config = load_config()
    db_path = get_absolute_db_path(config)
    output_dir = get_absolute_output_dir(config)
    try:
        backup_path = create_backup(
            app_root=APP_ROOT,
            backup_dir=get_backup_dir(),
            config_path=CONFIG_PATH,
            data_dir=db_path.parent,
            output_dir=output_dir,
            db_path=db_path,
            reason="manual",
        )
    except Exception:
        return jsonify({"ok": False, "message": "Não foi possível gerar o backup geral."}), 500
    return jsonify(
        {
            "ok": True,
            "message": f"Backup geral criado com sucesso: {backup_path.name}",
            "filename": backup_path.name,
        }
    )


@app.get("/admin/backup/download/<path:filename>")
@require_admin_page
def admin_backup_download(filename):
    backup_path = get_managed_backup_file_path(get_backup_dir(), filename)
    if backup_path is None:
        return redirect(url_for("admin_page", _anchor="backup-tools"))

    return send_from_directory(
        get_backup_dir(),
        backup_path.name,
        as_attachment=True,
        download_name=backup_path.name,
        mimetype="application/zip",
    )


@app.post("/admin/backup/restore")
@require_admin
def admin_backup_restore():
    upload = request.files.get("backup_file")
    filename = ""
    zip_bytes = b""

    if upload and upload.filename:
        filename = Path(upload.filename).name
        if not filename.lower().endswith(".zip"):
            return jsonify({"ok": False, "message": "Envie um arquivo .zip para restauração."}), 400
        zip_bytes = upload.read()
    else:
        data = request.get_json(silent=True) or request.form
        filename = _clean(data.get("filename"))
        if not filename:
            return jsonify({"ok": False, "message": "Selecione um backup geral para restaurar."}), 400

        backup_path = get_managed_backup_file_path(get_backup_dir(), filename)
        if backup_path is None:
            return jsonify({"ok": False, "message": "Backup não encontrado."}), 404
        zip_bytes = backup_path.read_bytes()

    if not zip_bytes:
        return jsonify({"ok": False, "message": "Não foi possível ler o backup informado."}), 400

    ok, message = restore_backup(
        zip_bytes=zip_bytes,
        app_root=APP_ROOT,
        backup_dir=get_backup_dir(),
        config_path=CONFIG_PATH,
        current_config=load_config(),
        default_db_path=APP_ROOT / "data" / "etiquetas.db",
        default_output_dir=APP_ROOT / "output",
    )
    if not ok:
        return jsonify({"ok": False, "message": message}), 400

    bootstrap_database_cached.cache_clear()
    return jsonify({"ok": True, "message": message})


@app.post("/admin/login")
def admin_login():
    config = load_config()
    data = request.get_json(silent=True) or request.form
    provided_password = _clean(data.get("password"))

    if provided_password and provided_password == get_admin_password(config):
        session["is_admin"] = True
        return jsonify({"ok": True, "message": "Acesso liberado."})

    return jsonify({"ok": False, "message": "Senha inv\u00e1lida."}), 401


@app.post("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"ok": True})


@app.post("/admin/material")
def admin_material():
    config = load_config()
    db_path = get_db_path(config)

    data = request.get_json(silent=True) or request.form
    code = data.get("code", "")
    description = data.get("description", "")

    if not upsert_material(db_path, code, description):
        return jsonify({"ok": False, "message": "Informe c\u00f3digo e descri\u00e7\u00e3o do material."}), 400

    return jsonify({"ok": True, "message": "Material salvo com sucesso."})


@app.post("/admin/fornecedor")
def admin_fornecedor():
    config = load_config()
    db_path = get_db_path(config)

    data = request.get_json(silent=True) or request.form
    code = data.get("code", "")
    name = data.get("name", "")

    if not upsert_supplier(db_path, code, name):
        return jsonify({"ok": False, "message": "Informe c\u00f3digo e nome do fornecedor."}), 400

    return jsonify({"ok": True, "message": "Fornecedor salvo com sucesso."})


@app.get("/admin/api/materiais")
def admin_api_materiais():
    config = load_config()
    db_path = get_db_path(config)
    search = _clean(request.args.get("q"))
    page = request.args.get("page", "1")
    per_page = request.args.get("per_page", "25")
    payload = list_materials_paginated(db_path, search=search, page=page, per_page=per_page)
    return jsonify({"ok": True, **payload})


@app.get("/admin/api/fornecedores")
def admin_api_fornecedores():
    config = load_config()
    db_path = get_db_path(config)
    search = _clean(request.args.get("q"))
    page = request.args.get("page", "1")
    per_page = request.args.get("per_page", "25")
    payload = list_suppliers_paginated(db_path, search=search, page=page, per_page=per_page)
    return jsonify({"ok": True, **payload})


@app.post("/admin/cadastros/materiais/importar")
def admin_importar_materiais():
    config = load_config()
    db_path = get_db_path(config)
    upload = request.files.get("arquivo_csv")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "message": "Selecione um arquivo CSV de materiais."}), 400

    if not upload.filename.lower().endswith(".csv"):
        return jsonify({"ok": False, "message": "Envie um arquivo .csv para importar materiais."}), 400

    result = import_materials_csv(db_path, upload.read())
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.post("/admin/cadastros/fornecedores/importar")
def admin_importar_fornecedores():
    config = load_config()
    db_path = get_db_path(config)
    upload = request.files.get("arquivo_csv")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "message": "Selecione um arquivo CSV de fornecedores."}), 400

    if not upload.filename.lower().endswith(".csv"):
        return jsonify({"ok": False, "message": "Envie um arquivo .csv para importar fornecedores."}), 400

    result = import_suppliers_csv(db_path, upload.read())
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


def _build_csv_model_response(filename: str, content: str):
    buffer = BytesIO(content.encode("utf-8"))
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="text/csv",
    )


@app.get("/admin/cadastros/modelo/materiais.csv")
def admin_modelo_materiais():
    return _build_csv_model_response(
        "materiais_modelo.csv",
        "codigo,descricao\n42031,CFF - SAE 1006 - ESP.= 1,90MM\n",
    )


@app.get("/admin/cadastros/modelo/fornecedores.csv")
def admin_modelo_fornecedores():
    return _build_csv_model_response(
        "fornecedores_modelo.csv",
        "codigo,nome\n1247,PANATLANTICA\n",
    )


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        Timer(1, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=is_debug_enabled(load_config()))

