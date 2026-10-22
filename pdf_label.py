from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


LAYOUT_A4_12 = "a4_12"
LAYOUT_A4_6 = "a4_6"
LAYOUT_LABEL_100X70 = "label_100x70"
LAYOUT_LABEL_140X70 = "label_140x70"
LABEL_ASPECT_RATIO = 100 / 70
IDENT_LABEL_WIDTH_MM = 90
IDENT_LABEL_HEIGHT_MM = 60
IDENT_PAGE_WIDTH_MM = 100
IDENT_PAGE_HEIGHT_MM = 70
IDENT_OFFSET_X_MM = 5
IDENT_OFFSET_Y_MM = 5
IDENT_A4_COLS = 2
IDENT_A4_ROWS = 3
IDENT_REFERENCE_WIDTH_MM = 190
IDENT_REFERENCE_HEIGHT_MM = 146
THERMAL_100X70_PAGE_WIDTH_MM = 100
THERMAL_100X70_PAGE_HEIGHT_MM = 70
THERMAL_100X70_CONTENT_WIDTH_MM = 90
THERMAL_100X70_CONTENT_HEIGHT_MM = 60
THERMAL_100X70_OFFSET_X_MM = 5
THERMAL_100X70_OFFSET_Y_MM = 5


def _is_thermal_label_mode(layout_mode: str) -> bool:
    return layout_mode in {LAYOUT_LABEL_100X70, LAYOUT_LABEL_140X70}


MATERIA_PRIMA_LABEL_TITLE = "Identifica\u00e7\u00e3o de Mat\u00e9ria Prima"
USINADOS_LABEL_TITLE = "Identifica\u00e7\u00e3o de Mat\u00e9ria Prima Usinados"
BENS_CONSUMO_LABEL_TITLE = "Indentifica\u00e7\u00e3o de Bens de Consumo"


def _label_title(label_profile: str | None) -> str:
    if label_profile == "usinados":
        return USINADOS_LABEL_TITLE
    if label_profile == "bens_consumo":
        return BENS_CONSUMO_LABEL_TITLE
    return MATERIA_PRIMA_LABEL_TITLE


def _safe(value):
    if value is None:
        return ""
    return str(value).strip()


def _fit_size(text, font_name, max_size, min_size, max_width, max_height):
    size = min(max_size, max_height)
    while size > min_size and pdfmetrics.stringWidth(text, font_name, size) > max_width:
        size -= 0.5
    return max(size, min_size)


def _draw_text(
    c,
    text,
    x,
    y,
    w,
    h,
    font="Helvetica",
    max_size=10,
    min_size=7,
    align="left",
    color=colors.black,
):
    text = _safe(text)
    if not text:
        return

    max_width = max(w - 2 * mm, 1)
    max_height = max((h - 1.2 * mm) * 0.85, min_size)
    size = _fit_size(text, font, max_size, min_size, max_width, max_height)
    c.setFont(font, size)
    c.setFillColor(color)

    if align == "center":
        tx = x + w / 2 - pdfmetrics.stringWidth(text, font, size) / 2
    elif align == "right":
        tx = x + w - pdfmetrics.stringWidth(text, font, size) - 1.2 * mm
    else:
        tx = x + 1.2 * mm

    ty = y + (h - size) / 2 + 0.3 * mm
    c.drawString(tx, ty, text)


def _cell(c, x, y, w, h, fill=None, stroke=colors.black, stroke_width=0.8):
    c.setLineWidth(stroke_width)
    c.setStrokeColor(stroke)
    c.setFillColor(fill if fill is not None else colors.white)
    c.rect(x, y, w, h, fill=1, stroke=1)


def _break_long_word(word: str, font_name: str, font_size: float, max_width: float):
    if not word:
        return [""]

    pieces = []
    current = ""
    for char in word:
        candidate = f"{current}{char}"
        if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
            pieces.append(current)
            current = char
        else:
            current = candidate

    if current:
        pieces.append(current)

    return pieces or [word]


def _wrap_text_lines(text: str, font_name: str, font_size: float, max_width: float):
    words = [part for part in _safe(text).split() if part]
    if not words:
        return []

    lines = []
    current = ""

    for word in words:
        segments = [word]
        if pdfmetrics.stringWidth(word, font_name, font_size) > max_width:
            segments = _break_long_word(word, font_name, font_size, max_width)

        for segment in segments:
            candidate = segment if not current else f"{current} {segment}"
            if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                lines.append(current)
                current = segment
            else:
                current = candidate

    if current:
        lines.append(current)

    return lines


def _truncate_with_ellipsis(text: str, font_name: str, font_size: float, max_width: float):
    text = _safe(text)
    if not text:
        return ""

    ellipsis = "..."
    if pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
        return text

    while text and pdfmetrics.stringWidth(f"{text}{ellipsis}", font_name, font_size) > max_width:
        text = text[:-1].rstrip()

    return f"{text}{ellipsis}" if text else ellipsis


def _clip_lines_with_ellipsis(lines: list[str], font_name: str, font_size: float, max_width: float, max_lines: int):
    if len(lines) <= max_lines:
        return lines

    clipped = lines[:max_lines]
    remainder = " ".join(lines[max_lines - 1 :])
    clipped[-1] = _truncate_with_ellipsis(remainder, font_name, font_size, max_width)
    return clipped


def draw_text_box(
    c,
    text,
    x,
    y,
    width,
    height,
    font_name="Helvetica-Bold",
    max_font_size=8,
    min_font_size=5,
    max_lines=2,
    align="center",
    color=colors.black,
):
    text = _safe(text)
    if not text:
        return

    padding_x = min(1.6 * mm, max(width * 0.045, 0.9 * mm))
    padding_y = min(1.2 * mm, max(height * 0.08, 0.6 * mm))
    usable_width = max(width - 2 * padding_x, 1)
    usable_height = max(height - 2 * padding_y, 1)
    leading = 1.08

    chosen_size = min_font_size
    chosen_lines = []

    size = float(max_font_size)
    while size >= min_font_size:
        lines = _wrap_text_lines(text, font_name, size, usable_width)
        line_height = size * leading
        if lines and len(lines) <= max_lines and line_height * len(lines) <= usable_height:
            chosen_size = size
            chosen_lines = lines
            break
        size -= 0.5

    if not chosen_lines:
        chosen_size = float(min_font_size)
        wrapped = _wrap_text_lines(text, font_name, chosen_size, usable_width)
        chosen_lines = _clip_lines_with_ellipsis(wrapped, font_name, chosen_size, usable_width, max_lines)

        line_height = chosen_size * leading
        max_fit_lines = max(1, min(max_lines, int(usable_height // max(line_height, 1))))
        if len(chosen_lines) > max_fit_lines:
            chosen_lines = chosen_lines[:max_fit_lines]
            chosen_lines[-1] = _truncate_with_ellipsis(chosen_lines[-1], font_name, chosen_size, usable_width)

    c.setFont(font_name, chosen_size)
    c.setFillColor(color)

    line_height = chosen_size * leading
    total_height = line_height * len(chosen_lines)
    top_y = y + height - padding_y - max((usable_height - total_height) / 2, 0) - chosen_size

    for idx, line in enumerate(chosen_lines):
        line_width = pdfmetrics.stringWidth(line, font_name, chosen_size)
        if align == "center":
            tx = x + width / 2 - line_width / 2
        elif align == "right":
            tx = x + width - padding_x - line_width
        else:
            tx = x + padding_x

        ty = top_y - idx * line_height
        if ty < y + padding_y - 0.2 * mm:
            break
        c.drawString(tx, ty, line)


def draw_label(c, payload, logo_path: Path, box_x, box_y, box_w, box_h, *, compact=False, inner_margin=None):
    if inner_margin is not None:
        margin = max(float(inner_margin), 0)
        outer_stroke = 0.75 if compact else 1.0
        inner_stroke = 0.5 if compact else 0.7
        logo_w_limit = 28 * mm if compact else 34 * mm
    elif compact:
        margin = 0.8 * mm
        outer_stroke = 0.75
        inner_stroke = 0.5
        logo_w_limit = 28 * mm
    else:
        margin = max(1.2 * mm, min(box_w, box_h) * 0.03)
        outer_stroke = 1.0
        inner_stroke = 0.7
        logo_w_limit = 34 * mm

    x0 = box_x + margin
    y0 = box_y + margin
    w = max(box_w - 2 * margin, 20 * mm)
    h = max(box_h - 2 * margin, 20 * mm)

    beige = colors.HexColor("#F1E7BF")
    soft_gray = colors.HexColor("#ECECEC")
    light_white = colors.HexColor("#FAFAFA")
    border = colors.HexColor("#2C2C2C")

    _cell(c, x0, y0, w, h, fill=colors.white, stroke=border, stroke_width=outer_stroke)

    header_h = h * 0.165
    r1 = h * 0.127
    r2 = h * 0.095
    r3 = h * 0.253
    r4 = h * 0.089
    r5 = h * 0.089
    r6 = h * 0.089
    r7 = h - (header_h + r1 + r2 + r3 + r4 + r5 + r6)

    _cell(c, x0, y0 + h - header_h, w, header_h, fill=soft_gray, stroke=border, stroke_width=inner_stroke)

    logo_w = min(w * 0.22, logo_w_limit)
    if logo_path.exists():
        c.drawImage(
            str(logo_path),
            x0 + (1.1 * mm if compact else 1.4 * mm),
            y0 + h - header_h + (0.6 * mm if compact else 0.8 * mm),
            logo_w - 2 * mm,
            header_h - (1.2 * mm if compact else 1.6 * mm),
            preserveAspectRatio=True,
            mask="auto",
        )

    title = _label_title(_safe(payload.get("label_profile")))
    title_size = _fit_size(title, "Helvetica-Bold", 17 if compact else 18, 9, w * (0.66 if compact else 0.62), header_h * 0.62)
    c.setFont("Helvetica-Bold", title_size)
    c.setFillColor(colors.black)
    c.drawCentredString(x0 + w / 2 + (6.5 * mm if compact else 8 * mm), y0 + h - header_h / 2 - title_size * 0.25, title)

    y = y0 + h - header_h

    # Row 1: C\u00f3digo do produto / data
    lw = w * 0.68
    rw = w - lw
    _cell(c, x0, y - r1, lw, r1, fill=light_white, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + lw, y - r1, rw, r1, fill=light_white, stroke=border, stroke_width=inner_stroke)

    code_label_w = lw * 0.36
    _draw_text(c, "C\u00f3digo Produto:", x0, y - r1, code_label_w, r1, font="Helvetica-Bold", max_size=11, color=colors.black)
    _draw_text(c, _safe(payload.get("codigo")), x0 + code_label_w, y - r1, lw - code_label_w, r1, font="Helvetica-Bold", max_size=22, min_size=10, align="center", color=colors.black)

    _draw_text(c, "DATA", x0 + lw, y - r1, rw, r1, font="Helvetica-Bold", max_size=13, align="center", color=colors.black)

    y -= r1

    # Row 2: N\u00ba lote / data
    _cell(c, x0, y - r2, lw, r2, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + lw, y - r2, rw, r2, fill=beige, stroke=border, stroke_width=inner_stroke)
    _draw_text(c, "N\u00ba LOTE", x0, y - r2, lw, r2, font="Helvetica-Bold", max_size=12, align="center", color=colors.black)
    _draw_text(c, _safe(payload.get("data")), x0 + lw, y - r2, rw, r2, font="Helvetica-Bold", max_size=15, min_size=9, align="center", color=colors.black)

    y -= r2

    # Row 3: big lote / material description
    left_w = w * 0.43
    right_w = w - left_w
    _cell(c, x0, y - r3, left_w, r3, fill=beige, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + left_w, y - r3, right_w, r3, fill=soft_gray, stroke=border, stroke_width=inner_stroke)

    _draw_text(c, _safe(payload.get("lote")), x0, y - r3, left_w, r3, font="Helvetica-Bold", max_size=40, min_size=12, align="center", color=colors.black)
    draw_text_box(
        c,
        _safe(payload.get("material_desc")),
        x0 + left_w,
        y - r3,
        right_w,
        r3,
        font_name="Helvetica-Bold",
        max_font_size=18,
        min_font_size=6.5,
        max_lines=2,
        align="center",
        color=colors.black,
    )

    y -= r3

    # Row 4: insp / ref / dim1 x dim2
    c1 = w * 0.20
    c2 = w * 0.14
    c3 = w * 0.13
    c4 = w * 0.06
    c5 = w - (c1 + c2 + c3 + c4)

    x = x0
    for cw, fill in [(c1, soft_gray), (c2, light_white), (c3, beige), (c4, light_white), (c5, beige)]:
        _cell(c, x, y - r4, cw, r4, fill=fill, stroke=border, stroke_width=inner_stroke)
        x += cw

    _draw_text(c, "insp:", x0, y - r4, c1 * 0.42, r4, font="Helvetica-Bold", max_size=10, color=colors.black)
    _draw_text(c, _safe(payload.get("insp")), x0 + c1 * 0.42, y - r4, c1 * 0.58, r4, font="Helvetica-Bold", max_size=12, min_size=8, align="center", color=colors.black)

    _draw_text(c, "Ref:", x0 + c1, y - r4, c2 * 0.42, r4, font="Helvetica-Bold", max_size=10, color=colors.black)
    _draw_text(c, _safe(payload.get("ref")), x0 + c1 + c2 * 0.42, y - r4, c2 * 0.58, r4, font="Helvetica-Bold", max_size=16, min_size=8, align="center", color=colors.black)

    _draw_text(c, _safe(payload.get("dim1")), x0 + c1 + c2, y - r4, c3, r4, font="Helvetica-Bold", max_size=16, min_size=8, align="center", color=colors.black)
    _draw_text(c, "x", x0 + c1 + c2 + c3, y - r4, c4, r4, font="Helvetica-Bold", max_size=15, align="center", color=colors.black)
    _draw_text(c, _safe(payload.get("dim2")), x0 + c1 + c2 + c3 + c4, y - r4, c5, r4, font="Helvetica-Bold", max_size=16, min_size=8, align="center", color=colors.black)

    y -= r4

    # Row 5: fornecedor code / fornecedor name
    lfw = w * 0.43
    rfw = w - lfw
    _cell(c, x0, y - r5, lfw, r5, fill=light_white, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + lfw, y - r5, rfw, r5, fill=beige, stroke=border, stroke_width=inner_stroke)

    label_w = lfw * 0.56
    _draw_text(c, "Fornecedor:", x0, y - r5, label_w, r5, font="Helvetica-Bold", max_size=10, color=colors.black)
    _draw_text(c, _safe(payload.get("fornecedor")), x0 + label_w, y - r5, lfw - label_w, r5, font="Helvetica-Bold", max_size=14, min_size=8, align="center", color=colors.black)
    _draw_text(c, _safe(payload.get("fornecedor_nome")), x0 + lfw, y - r5, rfw, r5, font="Helvetica-Bold", max_size=20, min_size=8, align="center", color=colors.black)

    y -= r5

    # Row 6: PDC / Quant / NF
    c1 = w * 0.32
    c2 = w * 0.12
    c3 = w * 0.10
    c4 = w * 0.08
    c5 = w * 0.12
    c6 = w - (c1 + c2 + c3 + c4 + c5)

    x = x0
    for cw, fill in [(c1, soft_gray), (c2, beige), (c3, soft_gray), (c4, light_white), (c5, soft_gray), (c6, beige)]:
        _cell(c, x, y - r6, cw, r6, fill=fill, stroke=border, stroke_width=inner_stroke)
        x += cw

    _draw_text(c, "PDC:", x0, y - r6, c1 * 0.25, r6, font="Helvetica-Bold", max_size=10, color=colors.black)
    _draw_text(c, _safe(payload.get("pdc")), x0 + c1 * 0.25, y - r6, c1 * 0.75, r6, font="Helvetica-Bold", max_size=15, min_size=8, align="center", color=colors.black)

    _draw_text(c, "Quant:", x0 + c1, y - r6, c2, r6, font="Helvetica-Bold", max_size=10, color=colors.black)
    _draw_text(c, _safe(payload.get("quant")), x0 + c1 + c2, y - r6, c3, r6, font="Helvetica-Bold", max_size=18, min_size=8, align="center", color=colors.black)

    _draw_text(c, "NF:", x0 + c1 + c2 + c3, y - r6, c4, r6, font="Helvetica-Bold", max_size=10, color=colors.black)
    _draw_text(c, _safe(payload.get("nf")), x0 + c1 + c2 + c3 + c4, y - r6, c5 + c6, r6, font="Helvetica-Bold", max_size=15, min_size=8, align="center", color=colors.black)

    y -= r6

    # Row 7: OS / PALLET
    c1 = w * 0.10
    c2 = w * 0.30
    c3 = w * 0.18
    c4 = w - (c1 + c2 + c3)

    x = x0
    for cw, fill in [(c1, soft_gray), (c2, light_white), (c3, soft_gray), (c4, light_white)]:
        _cell(c, x, y - r7, cw, r7, fill=fill, stroke=border, stroke_width=inner_stroke)
        x += cw

    _draw_text(c, "O.S:", x0, y - r7, c1, r7, font="Helvetica-Bold", max_size=10, color=colors.black)
    _draw_text(c, _safe(payload.get("os")), x0 + c1, y - r7, c2, r7, font="Helvetica-Bold", max_size=13, min_size=8, align="center", color=colors.black)

    _draw_text(c, "PALLET:", x0 + c1 + c2, y - r7, c3, r7, font="Helvetica-Bold", max_size=10, color=colors.black)
    _draw_text(c, _safe(payload.get("pallet")), x0 + c1 + c2 + c3, y - r7, c4, r7, font="Helvetica-Bold", max_size=13, min_size=8, align="center", color=colors.black)


def _layout_spec(layout_mode: str):
    if layout_mode == LAYOUT_LABEL_100X70:
        page_w = THERMAL_100X70_PAGE_WIDTH_MM * mm
        page_h = THERMAL_100X70_PAGE_HEIGHT_MM * mm
        content_w = THERMAL_100X70_CONTENT_WIDTH_MM * mm
        content_h = THERMAL_100X70_CONTENT_HEIGHT_MM * mm
        offset_x = THERMAL_100X70_OFFSET_X_MM * mm
        offset_y = THERMAL_100X70_OFFSET_Y_MM * mm
        slots = [(offset_x, offset_y, content_w, content_h)]
        return page_w, page_h, slots

    if layout_mode == LAYOUT_LABEL_140X70:
        page_w = 140 * mm
        page_h = 70 * mm
        slots = [(0, 0, page_w, page_h)]
        return page_w, page_h, slots

    if layout_mode == LAYOUT_A4_6:
        # Backward compatibility for older saved UI value.
        layout_mode = LAYOUT_A4_12

    # A4 with 12 labels of 90.5 x 44 mm.
    page_w = 210 * mm
    page_h = 297 * mm
    cols = 2
    rows = 6
    label_w = 90.5 * mm
    label_h = 44 * mm
    gap_x = 2.5 * mm
    gap_y = 0.4 * mm

    grid_w = cols * label_w + (cols - 1) * gap_x
    grid_h = rows * label_h + (rows - 1) * gap_y

    start_x = (page_w - grid_w) / 2
    start_y = (page_h - grid_h) / 2

    slots = []
    for row in range(rows):
        y = page_h - start_y - (row + 1) * label_h - row * gap_y
        for col in range(cols):
            x = start_x + col * (label_w + gap_x)
            slots.append((x, y, label_w, label_h))

    return page_w, page_h, slots


def _draw_usinados_label(c, payload, logo_path: Path, box_x, box_y, box_w, box_h):
    border = colors.HexColor("#1C1C1C")
    beige = colors.HexColor("#FFF0BE")
    soft_gray = colors.HexColor("#F0F0F0")
    white = colors.white

    x0 = box_x
    y0 = box_y
    w = box_w
    h = box_h

    outer_stroke = 1.4
    inner_stroke = 0.9

    _cell(c, x0, y0, w, h, fill=white, stroke=border, stroke_width=outer_stroke)

    header_h = h * 0.18
    supplier_h = h * 0.12
    code_h = h * 0.20
    detail_h = h * 0.40
    footer_h = h - (header_h + supplier_h + code_h + detail_h)

    current_y = y0 + h

    logo_w = w * 0.20
    title_w = w * 0.63
    seal_w = w - logo_w - title_w

    current_y -= header_h
    _cell(c, x0, current_y, logo_w, header_h, fill=white, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + logo_w, current_y, title_w, header_h, fill=white, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + logo_w + title_w, current_y, seal_w, header_h, fill=white, stroke=border, stroke_width=inner_stroke)

    if logo_path.exists():
        c.drawImage(
            str(logo_path),
            x0 + 4 * mm,
            current_y + 3 * mm,
            logo_w - 8 * mm,
            header_h - 8 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )

    _draw_text(
        c,
        _label_title(_safe(payload.get("label_profile"))),
        x0 + logo_w,
        current_y,
        title_w,
        header_h,
        font="Helvetica-Bold",
        max_size=15,
        min_size=8,
        align="center",
    )

    circle_r = min(seal_w, header_h) * 0.30
    circle_x = x0 + logo_w + title_w + seal_w / 2
    circle_y = current_y + header_h / 2
    c.setLineWidth(4)
    c.setStrokeColor(border)
    c.circle(circle_x, circle_y, circle_r, stroke=1, fill=0)

    current_y -= supplier_h
    col1 = w * 0.20
    col2 = w * 0.23
    col3 = w * 0.40
    col4 = w - col1 - col2 - col3
    for start_x, width, fill in (
        (x0, col1, soft_gray),
        (x0 + col1, col2, beige),
        (x0 + col1 + col2, col3, soft_gray),
        (x0 + col1 + col2 + col3, col4, soft_gray),
    ):
        _cell(c, start_x, current_y, width, supplier_h, fill=fill, stroke=border, stroke_width=inner_stroke)

    _draw_text(c, "Fornecedor:", x0, current_y, col1, supplier_h, font="Helvetica-Bold", max_size=10, min_size=6)
    _draw_text(c, _safe(payload.get("fornecedor")), x0 + col1, current_y, col2, supplier_h, font="Helvetica-Bold", max_size=16, min_size=8, align="center")
    _draw_text(c, _safe(payload.get("fornecedor_nome")), x0 + col1 + col2, current_y, col3, supplier_h, font="Helvetica-Bold", max_size=15, min_size=8, align="center")
    _draw_text(c, "Data", x0 + col1 + col2 + col3, current_y, col4, supplier_h, font="Helvetica-Bold", max_size=16, min_size=8, align="center")

    current_y -= code_h
    left_code = w * 0.43
    center_code = w * 0.40
    right_code = w - left_code - center_code
    _cell(c, x0, current_y, left_code, code_h, fill=soft_gray, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + left_code, current_y, center_code, code_h, fill=beige, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + left_code + center_code, current_y, right_code, code_h, fill=beige, stroke=border, stroke_width=inner_stroke)

    _draw_text(c, "C?digo:", x0, current_y, left_code, code_h, font="Helvetica-Bold", max_size=24, min_size=10, align="center")
    _draw_text(c, _safe(payload.get("codigo")), x0 + left_code, current_y, center_code, code_h, font="Helvetica-Bold", max_size=34, min_size=14, align="center")
    _draw_text(c, _safe(payload.get("data")), x0 + left_code + center_code, current_y, right_code, code_h, font="Helvetica-Bold", max_size=18, min_size=9, align="center")

    current_y -= detail_h
    left_detail = w * 0.43
    right_detail = w - left_detail
    _cell(c, x0, current_y, left_detail, detail_h, fill=white, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + left_detail, current_y, right_detail, detail_h, fill=white, stroke=border, stroke_width=inner_stroke)

    detail_rows = [
        ("NF:", _safe(payload.get("nf"))),
        ("Quant:", _safe(payload.get("quant"))),
        ("PDC:", _safe(payload.get("pdc"))),
        ("Insp:", _safe(payload.get("insp"))),
    ]
    row_h = detail_h / len(detail_rows)
    label_col = left_detail * 0.46
    value_col = left_detail - label_col
    for idx, (label, value) in enumerate(detail_rows):
        row_y = current_y + detail_h - (idx + 1) * row_h
        _cell(c, x0, row_y, label_col, row_h, fill=white, stroke=border, stroke_width=inner_stroke)
        _cell(c, x0 + label_col, row_y, value_col, row_h, fill=beige if value else white, stroke=border, stroke_width=inner_stroke)
        _draw_text(c, label, x0, row_y, label_col, row_h, font="Helvetica-Bold", max_size=11, min_size=6)
        _draw_text(c, value, x0 + label_col, row_y, value_col, row_h, font="Helvetica-Bold", max_size=17, min_size=8, align="center")

    draw_text_box(
        c,
        _safe(payload.get("material_desc")),
        x0 + left_detail,
        current_y,
        right_detail,
        detail_h,
        font_name="Helvetica-Bold",
        max_font_size=20,
        min_font_size=8,
        max_lines=3,
        align="center",
        color=colors.black,
    )

    current_y -= footer_h
    os_label_w = w * 0.20
    os_value_w = w - os_label_w
    _cell(c, x0, current_y, os_label_w, footer_h, fill=white, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + os_label_w, current_y, os_value_w, footer_h, fill=beige, stroke=border, stroke_width=inner_stroke)
    _draw_text(c, "OS:", x0, current_y, os_label_w, footer_h, font="Helvetica-Bold", max_size=14, min_size=8)
    _draw_text(c, _safe(payload.get("os")), x0 + os_label_w, current_y, os_value_w, footer_h, font="Helvetica-Bold", max_size=24, min_size=10, align="center")

def generate_label_pdf(output_dir: Path, logo_path: Path, payload: dict, copies: int = 1, layout_mode: str = LAYOUT_A4_12):
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_pdf = output_dir / f"etiqueta_{timestamp}.pdf"

    page_w, page_h, slots = _layout_spec(layout_mode)
    c = canvas.Canvas(str(out_pdf), pagesize=(page_w, page_h))
    compact = _is_thermal_label_mode(layout_mode) or layout_mode in {LAYOUT_A4_12, LAYOUT_A4_6}

    count = max(int(copies), 1)
    per_page = len(slots)

    for idx in range(count):
        slot = slots[idx % per_page]
        if layout_mode == LAYOUT_LABEL_140X70:
            _draw_usinados_label(c, payload, logo_path, slot[0], slot[1], slot[2], slot[3])
        else:
            inner_margin = 0 if layout_mode == LAYOUT_LABEL_100X70 else None
            draw_label(c, payload, logo_path, slot[0], slot[1], slot[2], slot[3], compact=compact, inner_margin=inner_margin)

        if idx < count - 1 and (idx + 1) % per_page == 0:
            c.showPage()

    c.save()
    return out_pdf


def _draw_multiline_text(
    c,
    text,
    x,
    y,
    w,
    h,
    *,
    font="Helvetica",
    font_size=14,
    leading=1.25,
    padding_x=3 * mm,
    padding_top=3 * mm,
    padding_bottom=4 * mm,
):
    text = _safe(text)
    if not text:
        return

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        lines = [text]

    c.setFont(font, font_size)
    c.setFillColor(colors.black)
    line_height = font_size * leading
    top_y = y + h - (font_size + padding_top)

    for idx, line in enumerate(lines):
        current_y = top_y - idx * line_height
        if current_y < y + padding_bottom:
            break
        c.drawString(x + padding_x, current_y, line)


def draw_identificacao_label(c, payload, logo_path: Path, box_x, box_y, box_w, box_h):
    border = colors.HexColor("#111111")
    x0 = box_x
    y0 = box_y
    w = box_w
    h = box_h
    scale_x = w / (IDENT_REFERENCE_WIDTH_MM * mm)
    scale_y = h / (IDENT_REFERENCE_HEIGHT_MM * mm)
    scale = min(scale_x, scale_y)

    def sx(value_mm):
        return value_mm * mm * scale_x

    def sy(value_mm):
        return value_mm * mm * scale_y

    outer_stroke = max(0.9, 2.2 * scale)
    inner_stroke = max(0.65, 1.8 * scale)

    _cell(c, x0, y0, w, h, fill=colors.white, stroke=border, stroke_width=outer_stroke)

    header_h = h * 0.16
    top_h = h * 0.08
    item_h = h * 0.10
    qty_h = h * 0.10
    insp_h = h * 0.09
    notes_h = h * 0.19
    footer_h = h - (header_h + top_h + item_h + qty_h + insp_h + notes_h)

    current_y = y0 + h

    # Header
    current_y -= header_h
    _cell(c, x0, current_y, w, header_h, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    logo_col_w = w * 0.28
    title_col_x = x0 + logo_col_w

    if logo_path.exists():
        c.drawImage(
            str(logo_path),
            x0 + sx(4.5),
            current_y + sy(2.3),
            max(logo_col_w - sx(9.5), sx(12)),
            max(header_h - sy(4.6), sy(3.8)),
            preserveAspectRatio=True,
            mask="auto",
        )

    draw_text_box(
        c,
        "METALUS INDUSTRIA MECANICA LTDA",
        x0 + sx(3.2),
        current_y + sy(0.4),
        max(logo_col_w - sx(6.4), sx(18)),
        sy(3.8),
        font_name="Helvetica-Bold",
        max_font_size=max(5.6, 8 * scale),
        min_font_size=4.2,
        max_lines=1,
        align="left",
        color=colors.black,
    )

    title = "Etiqueta de Identificação"
    title_size = _fit_size(title, "Helvetica-Bold", 28, 8, w - logo_col_w - sx(6), header_h * 0.48)
    c.setFont("Helvetica-Bold", title_size)
    c.setFillColor(colors.black)
    c.drawCentredString(title_col_x + (w - logo_col_w) / 2, current_y + header_h / 2 - title_size * 0.2, title)

    # Row 1
    current_y -= top_h
    left_w = w * 0.55
    mid_w = w * 0.22
    right_w = w - left_w - mid_w
    for start_x, width in ((x0, left_w), (x0 + left_w, mid_w), (x0 + left_w + mid_w, right_w)):
        _cell(c, start_x, current_y, width, top_h, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    _draw_text(c, f"O.S {payload.get('os', '')}", x0, current_y, left_w, top_h, font="Helvetica", max_size=20, min_size=10)
    _draw_text(c, "Data:", x0 + left_w, current_y, mid_w, top_h, font="Helvetica", max_size=18, min_size=10, align="center")
    _draw_text(c, payload.get("data", ""), x0 + left_w + mid_w, current_y, right_w, top_h, font="Helvetica", max_size=20, min_size=10, align="center")

    # Row 2
    current_y -= item_h
    _cell(c, x0, current_y, w, item_h, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    _draw_text(c, f"Código item: {payload.get('codigo_item', '')}", x0, current_y, w, item_h, font="Helvetica", max_size=20, min_size=10)

    # Row 3
    current_y -= qty_h
    half_w = w / 2
    _cell(c, x0, current_y, half_w, qty_h, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    _cell(c, x0 + half_w, current_y, half_w, qty_h, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    _draw_text(c, f"Quantidade lote: {payload.get('quantidade_lote', '')}", x0, current_y, half_w, qty_h, font="Helvetica", max_size=18, min_size=10)
    _draw_text(c, f"Quantidade NC: {payload.get('quantidade_nc', '')}", x0 + half_w, current_y, half_w, qty_h, font="Helvetica", max_size=18, min_size=10)

    # Row 4
    current_y -= insp_h
    _cell(c, x0, current_y, w, insp_h, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    _draw_text(c, f"Inspetor: {payload.get('inspetor', '')}", x0, current_y, w, insp_h, font="Helvetica", max_size=18, min_size=10)

    # Row 5
    current_y -= notes_h
    _cell(c, x0, current_y, w, notes_h, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    _draw_text(
        c,
        "Não conformidade:",
        x0,
        current_y + notes_h - sy(5.4),
        w,
        sy(4.6),
        font="Helvetica",
        max_size=max(8, 18 * scale),
        min_size=5,
        color=colors.black,
    )
    _draw_multiline_text(
        c,
        payload.get("nao_conformidade", ""),
        x0,
        current_y,
        w,
        max(notes_h - sy(5.8), sy(4)),
        font="Helvetica",
        font_size=max(5.5, 14 * scale),
        padding_x=sx(1.6),
        padding_top=sy(1.5),
        padding_bottom=sy(1.6),
    )

    # Footer
    current_y -= footer_h
    _cell(c, x0, current_y, w, footer_h, fill=colors.white, stroke=border, stroke_width=inner_stroke)
    seal_area_w = w * 0.28
    legend_x = x0 + seal_area_w
    c.setLineWidth(max(0.65, 1.8 * scale))
    circle_size = min(seal_area_w - sx(7), footer_h - sy(5))
    circle_x = x0 + (seal_area_w - circle_size) / 2
    circle_y = current_y + (footer_h - circle_size) / 2
    c.circle(circle_x + circle_size / 2, circle_y + circle_size / 2, circle_size / 2, fill=0, stroke=1)

    legends = [
        "Cor Laranja: Item aguardando liberação",
        "Cor Azul: Item aprovado para expedição",
        "Cor Vermelha: Material não conforme",
        "Cor Verde: Material aprovado (Conforme)",
    ]
    legend_pad_x = sx(2.4)
    legend_pad_y = sy(1.3)
    legend_row_h = max((footer_h - 2 * legend_pad_y) / len(legends), sy(2.8))
    for index, line in enumerate(legends):
        row_y = current_y + footer_h - legend_pad_y - (index + 1) * legend_row_h
        draw_text_box(
            c,
            line,
            legend_x + legend_pad_x,
            row_y,
            max(w - seal_area_w - legend_pad_x - sx(1.4), sx(10)),
            legend_row_h,
            font_name="Helvetica",
            max_font_size=max(5.8, 12 * scale),
            min_font_size=4.4,
            max_lines=1,
            align="left",
            color=colors.black,
        )


def _identificacao_a4_slots():
    page_w = 210 * mm
    page_h = 297 * mm
    slot_w = IDENT_PAGE_WIDTH_MM * mm
    slot_h = IDENT_PAGE_HEIGHT_MM * mm
    label_w = IDENT_LABEL_WIDTH_MM * mm
    label_h = IDENT_LABEL_HEIGHT_MM * mm
    offset_x = IDENT_OFFSET_X_MM * mm
    offset_y = IDENT_OFFSET_Y_MM * mm

    grid_w = IDENT_A4_COLS * slot_w
    grid_h = IDENT_A4_ROWS * slot_h
    start_x = (page_w - grid_w) / 2
    start_y = (page_h - grid_h) / 2

    slots = []
    for row in range(IDENT_A4_ROWS):
        slot_y = page_h - start_y - (row + 1) * slot_h
        for col in range(IDENT_A4_COLS):
            slot_x = start_x + col * slot_w
            slots.append((slot_x + offset_x, slot_y + offset_y, label_w, label_h))

    return page_w, page_h, slots


def generate_identificacao_pdf(output_dir: Path, logo_path: Path, payload: dict, copies: int = 1):
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_pdf = output_dir / f"identificacao_{timestamp}.pdf"
    page_w, page_h, slots = _identificacao_a4_slots()

    c = canvas.Canvas(str(out_pdf), pagesize=(page_w, page_h))
    count = max(int(copies), 1)
    per_page = len(slots)

    for idx in range(count):
        slot = slots[idx % per_page]
        draw_identificacao_label(c, payload, logo_path, slot[0], slot[1], slot[2], slot[3])
        if idx < count - 1 and (idx + 1) % per_page == 0:
            c.showPage()

    c.save()
    return out_pdf


def generate_identificacao_batch_pdf(output_dir: Path, logo_path: Path, payloads: list[dict]):
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_pdf = output_dir / f"identificacao_lote_{timestamp}.pdf"
    page_w, page_h, slots = _identificacao_a4_slots()

    c = canvas.Canvas(str(out_pdf), pagesize=(page_w, page_h))
    rows = payloads or [{}]
    per_page = len(slots)

    for idx, payload in enumerate(rows):
        slot = slots[idx % per_page]
        draw_identificacao_label(c, payload, logo_path, slot[0], slot[1], slot[2], slot[3])
        if idx < len(rows) - 1 and (idx + 1) % per_page == 0:
            c.showPage()

    c.save()
    return out_pdf
