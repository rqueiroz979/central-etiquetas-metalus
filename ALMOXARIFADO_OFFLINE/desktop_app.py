import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
import unicodedata
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from database import (
    get_lookup_counts,
    init_db,
    list_materials_paginated,
    list_suppliers_paginated,
    lookup_material,
    lookup_supplier,
    normalize_code,
    upsert_material,
    upsert_supplier,
)
from pdf_label import generate_label_pdf


APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "config.json"
DEFAULT_DB_PATH = APP_ROOT / "data" / "etiquetas.db"
SESSION_OUTPUT_DIR = Path(tempfile.gettempdir()) / "almoxarifado_offline" / str(os.getpid())

MODELS = {
    "Matéria-Prima": {"layout_mode": "a4_12", "label_profile": "materia_prima"},
    "Matéria-Prima Usinados": {"layout_mode": "label_140x70", "label_profile": "usinados"},
    "Bens de Consumo": {"layout_mode": "label_140x70", "label_profile": "bens_consumo"},
}

LIGHT = {
    "app_bg": "#eeeae3",
    "shell": "#f8f7f3",
    "card": "#fffdf8",
    "soft": "#fffaf0",
    "logo": "#ffffff",
    "text": "#172033",
    "title": "#14233d",
    "muted": "#637083",
    "field": "#46556b",
    "input": "#ffffff",
    "border": "#d8cfc2",
    "accent": "#b85d50",
    "accent_active": "#a94f44",
    "tab": "#ead4cc",
}

DARK = {
    "app_bg": "#171a1f",
    "shell": "#20242b",
    "card": "#252a33",
    "soft": "#2c3038",
    "logo": "#ffffff",
    "text": "#eef1f5",
    "title": "#f6f1e8",
    "muted": "#b8c0cc",
    "field": "#c8d0dc",
    "input": "#181b21",
    "border": "#434956",
    "accent": "#c66a5e",
    "accent_active": "#d57a6d",
    "tab": "#3b3132",
}


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def path_from_config(config, key, fallback):
    value = str(config.get(key) or "").strip()
    path = Path(value) if value else fallback
    return path if path.is_absolute() else APP_ROOT / path


def open_file(path: Path):
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - user opens a local generated file.
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path)])


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


def import_lookup_table(db_path: Path, file_bytes: bytes):
    text = decode_csv_bytes(file_bytes)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return {"ok": False, "message": "Arquivo sem cabeçalho."}

    field_map = {normalize_header(header): header for header in reader.fieldnames}
    created_or_updated_materials = 0
    created_or_updated_suppliers = 0
    ignored = 0

    for row in reader:
        material_code = normalize_code(
            extract_value(row, field_map, ["codigo_material", "codigo_produto", "codigo item", "codigo", "cod"])
        )
        material_desc = extract_value(row, field_map, ["descricao", "descricao_produto", "descricao_material", "produto", "material"])

        supplier_code = normalize_code(
            extract_value(row, field_map, ["codigo_fornecedor", "fornecedor_codigo", "codigo fornecedor", "cod_fornecedor"])
        )
        supplier_name = extract_value(row, field_map, ["nome_fornecedor", "fornecedor_nome", "fornecedor", "razao_social"])

        generic_code = normalize_code(extract_value(row, field_map, ["codigo", "cod"]))
        generic_name = extract_value(row, field_map, ["nome"])
        if not supplier_code and not material_desc and generic_code and generic_name:
            supplier_code = generic_code
            supplier_name = generic_name

        changed = False
        if material_code and material_desc:
            upsert_material(db_path, material_code, material_desc)
            created_or_updated_materials += 1
            changed = True

        if supplier_code and supplier_name:
            upsert_supplier(db_path, supplier_code, supplier_name)
            created_or_updated_suppliers += 1
            changed = True

        if not changed:
            ignored += 1

    return {
        "ok": True,
        "materials": created_or_updated_materials,
        "suppliers": created_or_updated_suppliers,
        "ignored": ignored,
        "message": f"Importados: {created_or_updated_materials} materiais, {created_or_updated_suppliers} fornecedores, {ignored} ignorados.",
    }


class AlmoxarifadoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ALMOXARIFADO")
        self.geometry("1180x820")
        self.minsize(980, 700)

        self.config_data = load_config()
        self.db_path = path_from_config(self.config_data, "db_path", DEFAULT_DB_PATH)
        self.output_dir = SESSION_OUTPUT_DIR
        self.logo_path = APP_ROOT / "static" / "logo-metalus.png"
        self.last_pdf_path = None
        self.vars = {}
        self.logo_image = None
        self.dark_mode = tk.BooleanVar(value=False)
        self.cadastros_window = None

        init_db(self.db_path)
        shutil.rmtree(self.output_dir, ignore_errors=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self._configure_style()
        self._build_ui()
        self._refresh_counts()
        self._set_default_values()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    @property
    def colors(self):
        return DARK if self.dark_mode.get() else LIGHT

    def on_close(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)
        self.destroy()

    def _configure_style(self):
        c = self.colors
        self.configure(bg=c["app_bg"])
        self.style.configure("TFrame", background=c["app_bg"])
        self.style.configure("Shell.TFrame", background=c["shell"], relief="solid", borderwidth=1)
        self.style.configure("Card.TFrame", background=c["card"], relief="solid", borderwidth=1)
        self.style.configure("Soft.TFrame", background=c["soft"], relief="solid", borderwidth=1)
        self.style.configure("Logo.TFrame", background=c["logo"], relief="solid", borderwidth=1)
        self.style.configure("TLabel", background=c["app_bg"], foreground=c["text"], font=("Segoe UI", 10))
        self.style.configure("Card.TLabel", background=c["card"], foreground=c["text"], font=("Segoe UI", 10))
        self.style.configure("Soft.TLabel", background=c["soft"], foreground=c["text"], font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", background=c["card"], foreground=c["title"], font=("Segoe UI", 30, "bold"))
        self.style.configure("Section.TLabel", background=c["card"], foreground=c["title"], font=("Segoe UI", 18, "bold"))
        self.style.configure("PanelTitle.TLabel", background=c["soft"], foreground=c["title"], font=("Segoe UI", 12, "bold"))
        self.style.configure("Field.TLabel", background=c["card"], foreground=c["field"], font=("Segoe UI", 8, "bold"))
        self.style.configure("SoftField.TLabel", background=c["soft"], foreground=c["field"], font=("Segoe UI", 8, "bold"))
        self.style.configure("Muted.TLabel", background=c["card"], foreground=c["muted"], font=("Segoe UI", 9))
        self.style.configure("Status.TLabel", background=c["card"], foreground=c["muted"], font=("Segoe UI", 9))
        self.style.configure("TEntry", padding=8, fieldbackground=c["input"], foreground=c["text"], bordercolor=c["border"])
        self.style.configure("TCombobox", padding=8, fieldbackground=c["input"], foreground=c["text"], bordercolor=c["border"])
        self.style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8), background=c["soft"], foreground=c["text"])
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 10), background=c["accent"], foreground="#ffffff")
        self.style.configure("Tab.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 10), background=c["tab"], foreground=c["text"])
        self.style.map("Primary.TButton", background=[("active", c["accent_active"]), ("pressed", c["accent_active"])], foreground=[("active", "#ffffff")])
        self.style.configure("Treeview", background=c["input"], fieldbackground=c["input"], foreground=c["text"], rowheight=28)
        self.style.configure("Treeview.Heading", background=c["soft"], foreground=c["field"], font=("Segoe UI", 8, "bold"))

    def toggle_theme(self):
        self._configure_style()
        if self.cadastros_window and self.cadastros_window.winfo_exists():
            self.cadastros_window.configure(bg=self.colors["app_bg"])

    def _build_ui(self):
        shell = ttk.Frame(self, style="Shell.TFrame", padding=18)
        shell.pack(fill="both", expand=True, padx=42, pady=28)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        self._build_header(shell)
        form_card = ttk.Frame(shell, style="Card.TFrame", padding=18)
        form_card.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        self._build_form(form_card)

    def _build_header(self, parent):
        header = ttk.Frame(parent, style="Card.TFrame", padding=18)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        logo_box = ttk.Frame(header, style="Logo.TFrame", padding=10, width=150, height=112)
        logo_box.grid(row=0, column=0, sticky="w")
        logo_box.grid_propagate(False)
        try:
            image = tk.PhotoImage(file=str(self.logo_path))
            divisor = max(1, image.width() // 120, image.height() // 82)
            self.logo_image = image.subsample(divisor, divisor)
            tk.Label(logo_box, image=self.logo_image, bg="#ffffff", bd=0).pack(expand=True)
        except Exception:
            tk.Label(logo_box, text="METALUS", bg="#ffffff", fg="#14233d", font=("Segoe UI", 16, "bold"), bd=0).pack(expand=True)

        ttk.Label(header, text="Almoxarifado", style="Title.TLabel").grid(row=0, column=1, sticky="w", padx=22)

        right = ttk.Frame(header, style="Card.TFrame")
        right.grid(row=0, column=2, sticky="e")
        ttk.Checkbutton(right, variable=self.dark_mode, command=self.toggle_theme).pack(anchor="e", pady=(0, 16))

        count_card = ttk.Frame(right, style="Card.TFrame", padding=(14, 12))
        count_card.pack(anchor="e")
        ttk.Label(count_card, text="Cadastros", style="Card.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.counts_label = ttk.Label(count_card, text="", style="Muted.TLabel")
        self.counts_label.pack(anchor="w", pady=(6, 8))
        ttk.Button(count_card, text="Abrir", command=self.open_cadastros).pack(anchor="e")

    def _build_form(self, parent):
        for column in range(12):
            parent.columnconfigure(column, weight=1, uniform="form")
        ttk.Label(parent, text="Etiqueta de Produção", style="Section.TLabel").grid(row=0, column=0, columnspan=12, sticky="w")
        self.vars["model_label"] = tk.StringVar(value="Matéria-Prima")
        self._add_combo(parent, "model_label", "Tipo de etiqueta", 1, 0, list(MODELS.keys()), columnspan=3)
        self._add_entry(parent, "codigo", "Código do Produto", 1, 3, columnspan=4)
        self._add_entry(parent, "data", "Data", 1, 7, columnspan=2)
        self._add_entry(parent, "lote", "Nº Lote", 1, 9, columnspan=3)

        details = ttk.Frame(parent, style="Card.TFrame", padding=14)
        details.grid(row=2, column=0, columnspan=12, sticky="ew", pady=(12, 0))
        for column in range(12):
            details.columnconfigure(column, weight=1, uniform="details")
        self._add_entry(details, "material_desc", "Descrição do material", 0, 0, columnspan=12)
        self._add_entry(details, "insp", "Insp.", 1, 0, columnspan=3)
        self._add_entry(details, "ref", "Ref.", 1, 3, columnspan=3)
        self._add_entry(details, "dim1", "Dimensão 1", 1, 6, columnspan=3)
        self._add_entry(details, "dim2", "Dimensão 2", 1, 9, columnspan=3)
        self._add_entry(details, "fornecedor", "Fornecedor (código)", 2, 0, columnspan=5)
        self._add_entry(details, "fornecedor_nome", "Nome do fornecedor", 2, 5, columnspan=7)

        bottom = ttk.Frame(parent, style="Card.TFrame")
        bottom.grid(row=3, column=0, columnspan=12, sticky="nsew", pady=(14, 0))
        bottom.columnconfigure(0, weight=7)
        bottom.columnconfigure(1, weight=6)
        complement = ttk.Frame(bottom, style="Soft.TFrame", padding=14)
        complement.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        for column in range(6):
            complement.columnconfigure(column, weight=1, uniform="comp")
        ttk.Label(complement, text="Dados Complementares", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=6, sticky="w")
        self._add_entry(complement, "pdc", "PDC", 1, 0, columnspan=2, soft=True)
        self._add_entry(complement, "quant", "Quant.", 1, 2, columnspan=2, soft=True)
        self._add_entry(complement, "nf", "NF", 1, 4, columnspan=2, soft=True)
        self._add_entry(complement, "os", "O.S.", 2, 0, columnspan=2, soft=True)
        self._add_entry(complement, "pallet", "Pallet", 2, 2, columnspan=2, soft=True)

        print_panel = ttk.Frame(bottom, style="Soft.TFrame", padding=14)
        print_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        print_panel.columnconfigure(0, weight=1)
        ttk.Label(print_panel, text="Configuração de Impressão", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        self._add_entry(print_panel, "copies", "Quantidade de etiquetas", 1, 0, soft=True)
        ttk.Button(print_panel, text="Gerar Etiqueta", style="Primary.TButton", command=self.generate_pdf).grid(row=2, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(print_panel, text="Abrir último PDF", command=self.open_last_pdf).grid(row=3, column=0, sticky="ew", pady=(8, 0))

        actions = ttk.Frame(parent, style="Card.TFrame")
        actions.grid(row=4, column=0, columnspan=12, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Buscar dados", command=self.lookup_data).pack(side="left")
        ttk.Button(actions, text="Limpar", command=self.clear_form).pack(side="left", padx=8)
        self.status_label = ttk.Label(parent, text="", style="Status.TLabel")
        self.status_label.grid(row=5, column=0, columnspan=12, sticky="ew", pady=(8, 0))
        self.vars["codigo"].trace_add("write", lambda *_: self.after(250, self.lookup_data))
        self.vars["fornecedor"].trace_add("write", lambda *_: self.after(250, self.lookup_data))

    def _add_entry(self, parent, key, label, row, column, columnspan=1, soft=False):
        self.vars[key] = tk.StringVar()
        frame = ttk.Frame(parent, style="Soft.TFrame" if soft else "Card.TFrame")
        frame.grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=7, pady=7)
        ttk.Label(frame, text=label, style="SoftField.TLabel" if soft else "Field.TLabel").pack(anchor="w")
        entry = ttk.Entry(frame, textvariable=self.vars[key])
        entry.pack(fill="x", pady=(5, 0))
        return entry

    def _add_combo(self, parent, key, label, row, column, values, columnspan=1, soft=False):
        frame = ttk.Frame(parent, style="Soft.TFrame" if soft else "Card.TFrame")
        frame.grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=7, pady=7)
        ttk.Label(frame, text=label, style="SoftField.TLabel" if soft else "Field.TLabel").pack(anchor="w")
        combo = ttk.Combobox(frame, textvariable=self.vars[key], values=values, state="readonly")
        combo.pack(fill="x", pady=(5, 0))
        return combo

    def open_cadastros(self):
        if self.cadastros_window and self.cadastros_window.winfo_exists():
            self.cadastros_window.lift()
            return
        self.cadastros_window = CadastrosWindow(self)

    def _set_default_values(self):
        self.vars["data"].set(datetime.now().strftime("%d/%m/%y"))
        self.vars["ref"].set("0,00")
        self.vars["dim1"].set("1200")
        self.vars["dim2"].set("2000")
        self.vars["copies"].set("1")

    def _refresh_counts(self):
        material_count, supplier_count = get_lookup_counts(self.db_path)
        self.counts_label.configure(text=f"{material_count} materiais | {supplier_count} fornecedores")

    def lookup_data(self):
        code = normalize_code(self.vars["codigo"].get())
        supplier_code = normalize_code(self.vars["fornecedor"].get())
        if code:
            material_desc = lookup_material(self.db_path, code)
            if material_desc and not self.vars["material_desc"].get().strip():
                self.vars["material_desc"].set(material_desc)
        if supplier_code:
            supplier_name = lookup_supplier(self.db_path, supplier_code)
            if supplier_name and not self.vars["fornecedor_nome"].get().strip():
                self.vars["fornecedor_nome"].set(supplier_name)

    def build_payload(self):
        model = MODELS.get(self.vars["model_label"].get(), MODELS["Matéria-Prima"])
        payload = {
            "codigo": self.vars["codigo"].get().strip(),
            "data": self.vars["data"].get().strip(),
            "lote": self.vars["lote"].get().strip(),
            "material": normalize_code(self.vars["codigo"].get()),
            "material_desc": self.vars["material_desc"].get().strip(),
            "insp": self.vars["insp"].get().strip(),
            "ref": self.vars["ref"].get().strip(),
            "dim1": self.vars["dim1"].get().strip(),
            "dim2": self.vars["dim2"].get().strip(),
            "fornecedor": normalize_code(self.vars["fornecedor"].get()),
            "fornecedor_nome": self.vars["fornecedor_nome"].get().strip(),
            "pdc": self.vars["pdc"].get().strip(),
            "quant": self.vars["quant"].get().strip(),
            "nf": self.vars["nf"].get().strip(),
            "os": self.vars["os"].get().strip(),
            "pallet": self.vars["pallet"].get().strip(),
            "label_profile": model["label_profile"],
            "layout_mode": model["layout_mode"],
        }
        if not payload["material_desc"] and payload["material"]:
            payload["material_desc"] = lookup_material(self.db_path, payload["material"])
        if not payload["fornecedor_nome"] and payload["fornecedor"]:
            payload["fornecedor_nome"] = lookup_supplier(self.db_path, payload["fornecedor"])
        try:
            copies = max(1, min(300, int(self.vars["copies"].get().strip() or "1")))
        except ValueError:
            copies = 1
        return payload, copies, model["layout_mode"]

    def generate_pdf(self):
        payload, copies, layout_mode = self.build_payload()
        if not payload["codigo"]:
            messagebox.showwarning("Campo obrigatório", "Informe o código do produto.")
            return
        try:
            pdf_path = generate_label_pdf(self.output_dir, self.logo_path, payload, copies=copies, layout_mode=layout_mode)
        except Exception as exc:
            messagebox.showerror("Erro ao gerar PDF", f"Não foi possível gerar a etiqueta.\n\n{exc}")
            return
        if self.last_pdf_path and self.last_pdf_path != pdf_path and self.last_pdf_path.exists():
            try:
                self.last_pdf_path.unlink()
            except Exception:
                pass
        self.last_pdf_path = pdf_path
        self.status_label.configure(text=f"PDF gerado: {pdf_path.name}")
        if messagebox.askyesno("PDF gerado", "Etiqueta gerada. Abrir PDF?"):
            open_file(pdf_path)

    def open_last_pdf(self):
        if not self.last_pdf_path or not self.last_pdf_path.exists():
            messagebox.showinfo("PDF", "Gere uma etiqueta primeiro.")
            return
        open_file(self.last_pdf_path)

    def clear_form(self):
        for var in self.vars.values():
            var.set("")
        self.vars["model_label"].set("Matéria-Prima")
        self._set_default_values()
        self.status_label.configure(text="")


class CadastrosWindow(tk.Toplevel):
    def __init__(self, app: AlmoxarifadoApp):
        super().__init__(app)
        self.app = app
        self.title("Cadastros")
        self.geometry("1120x800")
        self.minsize(960, 680)
        self.configure(bg=app.colors["app_bg"])
        self.section = "materials"
        self.page = 1
        self.per_page = tk.IntVar(value=5)
        self.search = tk.StringVar()
        self.code_var = tk.StringVar()
        self.label_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self._build()
        self.load_table()

    def _build(self):
        shell = ttk.Frame(self, style="Shell.TFrame", padding=18)
        shell.pack(fill="both", expand=True, padx=24, pady=20)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        top = ttk.Frame(shell, style="Shell.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        ttk.Button(top, text="← Almoxarifado", command=self.destroy).pack(side="left")
        ttk.Checkbutton(top, variable=self.app.dark_mode, command=self.app.toggle_theme).pack(side="right")

        head = ttk.Frame(shell, style="Card.TFrame", padding=18)
        head.grid(row=1, column=0, sticky="ew", pady=(14, 14))
        head.columnconfigure(1, weight=1)
        try:
            tk.Label(head, image=self.app.logo_image, bg="#ffffff", bd=0).grid(row=0, column=0, rowspan=3, sticky="w", padx=(0, 22))
        except Exception:
            ttk.Label(head, text="METALUS", style="Card.TLabel", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, rowspan=3, sticky="w", padx=(0, 22))
        ttk.Label(head, text="Cadastros", style="Section.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(head, text="Cadastro de materiais, produtos e fornecedores", style="Card.TLabel").grid(row=1, column=1, sticky="w", pady=(12, 0))
        self.header_counts = ttk.Label(head, text="", style="Muted.TLabel")
        self.header_counts.grid(row=2, column=1, sticky="w", pady=(18, 0))

        body = ttk.Frame(shell, style="Card.TFrame", padding=18)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)
        ttk.Label(body, text="Cadastros", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Materiais, produtos e fornecedores usados no preenchimento automático.", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))

        tabs = ttk.Frame(body, style="Card.TFrame")
        tabs.grid(row=2, column=0, sticky="w", pady=(16, 14))
        ttk.Button(tabs, text="Materiais / Produtos", style="Primary.TButton", command=lambda: self.set_section("materials")).pack(side="left")
        ttk.Button(tabs, text="Fornecedores", style="Tab.TButton", command=lambda: self.set_section("suppliers")).pack(side="left", padx=(10, 0))

        forms = ttk.Frame(body, style="Card.TFrame")
        forms.grid(row=3, column=0, sticky="ew")
        forms.columnconfigure(0, weight=1)
        forms.columnconfigure(1, weight=1)

        import_card = ttk.Frame(forms, style="Card.TFrame", padding=16)
        import_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(import_card, text="Importar tabela", style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(import_card, text="CSV com materiais e fornecedores.", style="Muted.TLabel").pack(anchor="w", pady=(20, 14))
        ttk.Button(import_card, text="Escolher arquivo e importar", style="Primary.TButton", command=self.import_file).pack(anchor="w")

        edit_card = ttk.Frame(forms, style="Card.TFrame", padding=16)
        edit_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.edit_title = ttk.Label(edit_card, text="Material / Produto", style="Card.TLabel", font=("Segoe UI", 12, "bold"))
        self.edit_title.pack(anchor="w")
        self._field(edit_card, "Código", self.code_var)
        self.value_label = ttk.Label(edit_card, text="Descrição", style="Field.TLabel")
        self.value_label.pack(anchor="w", pady=(12, 0))
        ttk.Entry(edit_card, textvariable=self.label_var).pack(fill="x", pady=(5, 0))
        self.save_button = ttk.Button(edit_card, text="Salvar Material / Produto", style="Primary.TButton", command=self.save_record)
        self.save_button.pack(fill="x", pady=(14, 0))

        table_card = ttk.Frame(body, style="Card.TFrame", padding=16)
        table_card.grid(row=4, column=0, sticky="nsew", pady=(14, 0))
        table_card.columnconfigure(0, weight=1)
        table_card.rowconfigure(2, weight=1)
        self.table_title = ttk.Label(table_card, text="Materiais / Produtos cadastrados", style="Card.TLabel", font=("Segoe UI", 12, "bold"))
        self.table_title.grid(row=0, column=0, sticky="w")
        controls = ttk.Frame(table_card, style="Card.TFrame")
        controls.grid(row=0, column=1, sticky="e")
        ttk.Entry(controls, textvariable=self.search, width=34).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Buscar", command=self.search_table).pack(side="left")
        self.total_label = ttk.Label(table_card, text="", style="Card.TLabel")
        self.total_label.grid(row=1, column=0, sticky="w", pady=(8, 8))
        pager = ttk.Frame(table_card, style="Card.TFrame")
        pager.grid(row=1, column=1, sticky="e", pady=(8, 8))
        ttk.Label(pager, text="Exibir", style="Card.TLabel").pack(side="left", padx=(0, 6))
        ttk.Combobox(pager, textvariable=self.per_page, values=[5, 10, 25, 50], width=4, state="readonly").pack(side="left")
        ttk.Button(pager, text="Anterior", command=self.prev_page).pack(side="left", padx=8)
        self.page_label = ttk.Label(pager, text="", style="Card.TLabel")
        self.page_label.pack(side="left")
        ttk.Button(pager, text="Próxima", command=self.next_page).pack(side="left", padx=(8, 0))

        self.tree = ttk.Treeview(table_card, columns=("code", "label", "action"), show="headings", height=8)
        self.tree.heading("code", text="CÓDIGO")
        self.tree.heading("label", text="DESCRIÇÃO")
        self.tree.heading("action", text="AÇÕES")
        self.tree.column("code", width=160, anchor="w")
        self.tree.column("label", width=620, anchor="w")
        self.tree.column("action", width=130, anchor="center")
        self.tree.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.tree.bind("<Double-1>", self.edit_selected)
        ttk.Label(table_card, textvariable=self.status_var, style="Status.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _field(self, parent, label, variable):
        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor="w", pady=(14, 0))
        ttk.Entry(parent, textvariable=variable).pack(fill="x", pady=(5, 0))

    def set_section(self, section):
        self.section = section
        self.page = 1
        self.code_var.set("")
        self.label_var.set("")
        if section == "materials":
            self.edit_title.configure(text="Material / Produto")
            self.value_label.configure(text="Descrição")
            self.save_button.configure(text="Salvar Material / Produto")
            self.table_title.configure(text="Materiais / Produtos cadastrados")
            self.tree.heading("label", text="DESCRIÇÃO")
        else:
            self.edit_title.configure(text="Fornecedor")
            self.value_label.configure(text="Nome")
            self.save_button.configure(text="Salvar Fornecedor")
            self.table_title.configure(text="Fornecedores cadastrados")
            self.tree.heading("label", text="NOME")
        self.load_table()

    def current_data(self):
        if self.section == "materials":
            return list_materials_paginated(self.app.db_path, search=self.search.get(), page=self.page, per_page=self.per_page.get())
        return list_suppliers_paginated(self.app.db_path, search=self.search.get(), page=self.page, per_page=self.per_page.get())

    def load_table(self):
        data = self.current_data()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in data["items"]:
            self.tree.insert("", "end", values=(row["code"], row["label"], "duplo clique"))
        self.total_label.configure(text=f"Total: {data['total']}")
        self.page_label.configure(text=f"Página {data['page']} de {data['pages']}")
        materials, suppliers = get_lookup_counts(self.app.db_path)
        self.header_counts.configure(text=f"{materials} materiais • {suppliers} fornecedores")
        self.app._refresh_counts()
        self.total_pages = data["pages"]

    def search_table(self):
        self.page = 1
        self.load_table()

    def prev_page(self):
        if self.page > 1:
            self.page -= 1
            self.load_table()

    def next_page(self):
        if self.page < getattr(self, "total_pages", 1):
            self.page += 1
            self.load_table()

    def edit_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        code, label, _action = self.tree.item(selected[0], "values")
        self.code_var.set(code)
        self.label_var.set(label)

    def save_record(self):
        code = self.code_var.get()
        label = self.label_var.get()
        if self.section == "materials":
            ok = upsert_material(self.app.db_path, code, label)
            message = "Material / Produto salvo."
        else:
            ok = upsert_supplier(self.app.db_path, code, label)
            message = "Fornecedor salvo."
        if not ok:
            messagebox.showwarning("Cadastro", "Informe código e valor.")
            return
        self.status_var.set(message)
        self.code_var.set("")
        self.label_var.set("")
        self.load_table()

    def import_file(self):
        filename = filedialog.askopenfilename(parent=self, title="Importar tabela", filetypes=[("CSV", "*.csv"), ("Todos os arquivos", "*.*")])
        if not filename:
            return
        if not filename.lower().endswith(".csv"):
            messagebox.showwarning("Importar tabela", "Selecione um arquivo CSV.")
            return
        result = import_lookup_table(self.app.db_path, Path(filename).read_bytes())
        if not result["ok"]:
            messagebox.showwarning("Importar tabela", result["message"])
            return
        self.status_var.set(result["message"])
        self.load_table()


if __name__ == "__main__":
    AlmoxarifadoApp().mainloop()
