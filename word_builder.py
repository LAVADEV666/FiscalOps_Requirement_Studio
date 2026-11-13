"""
word_builder.py — Reconstrucción profesional en DOCX.

Renderiza el modelo documental (dict-based heredado) y los nuevos modelos
espaciales (TextBlock / TableBlock con coordenadas) en documentos Word
profesionales.

Características nuevas (v8.1):
  - Tablas nativas desde matrices de PP-Structure (document.add_table).
  - Jerarquía textual basada en coordenada X → estilos List Number / List Bullet.
  - Conservación de encabezados de tabla con w:tblHeader.
  - Compatible con word_audit.compare_document_to_docx.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.style import WD_STYLE_TYPE
from docx.section import Section

from text_normalizer import split_structured_lines
from document_model import ensure_document, TextBlock, TableBlock, HierarchicalNode, flatten_hierarchy
from docx.oxml.parser import parse_xml
from word_audit import block_bookmark
from template_store import load_template, marker_paragraph

# ---------------------------------------------------------------------------
# Paleta de colores FiscalOps
# ---------------------------------------------------------------------------
BLUE = RGBColor(31, 78, 121)
LIGHT = RGBColor(221, 235, 247)
GRAY = RGBColor(89, 89, 89)
BLACK = RGBColor(0, 0, 0)
LIGHT_GRAY = RGBColor(242, 242, 242)
WARN_YELLOW = RGBColor(156, 87, 0)

# ---------------------------------------------------------------------------
# Expresiones para reconocimiento de jerarquía en texto plano (legacy)
# ---------------------------------------------------------------------------
BULLET_RE = re.compile(r"^\s*[•✓✔▪]\s*(.+)$")
SUB_RE = re.compile(r"^\s*([a-z])\)\s+(.+)$", re.I)
QUESTION_RE = re.compile(r"^\s*[•]?\s*(¿.+?\?)(.*)$", re.I)


# ==============================================================================
# Utilidades de estilo DOCX
# ==============================================================================

def fmt(run, size: float = 9, bold: bool = False, italic: bool = False,
        color: RGBColor | None = BLACK) -> None:
    """Aplica tipografía Arial uniforme a un run."""
    run.font.name = "Arial"
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def shade(paragraph, fill: str) -> None:
    """Aplica sombreado de fondo a un párrafo (w:shd)."""
    ppr = paragraph._p.get_or_add_pPr()
    node = OxmlElement("w:shd")
    node.set(qn("w:fill"), fill)
    ppr.append(node)


def keep(paragraph) -> None:
    """Mantiene el párrafo pegado al siguiente (keepWithNext)."""
    paragraph.paragraph_format.keep_with_next = True


def add_title(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
    keep(p)
    r = p.add_run(text.upper())
    fmt(r, 11, True, False, BLUE)


def add_section(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    keep(p)
    shade(p, "DDEBF7")
    r = p.add_run("  " + text.upper())
    fmt(r, 9, True, False, BLUE)


def add_label(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(3)
    keep(p)
    r = p.add_run(text)
    fmt(r, 9, True)


def add_text(doc, text: str, indent: float = 0.0, first: float = 0.0,
             italic: bool = False, bold: bool = False, space: float = 3.0) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.left_indent = Cm(indent)
    p.paragraph_format.first_line_indent = Cm(first)
    p.paragraph_format.space_after = Pt(space)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(text.strip())
    fmt(r, 9, bold, italic)
    return p


def add_item(doc, text: str, level: int = 0, symbol: str = "•",
             italic: bool = True) -> None:
    """Agrega un elemento de lista con sangría progresiva."""
    left = 0.7 + level * 0.55
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.left_indent = Cm(left)
    p.paragraph_format.first_line_indent = Cm(-0.4)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(symbol + "\t" + text.strip())
    fmt(r, 9, False, italic)
    return p


def set_cell_shading(cell, fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    node = OxmlElement("w:shd")
    node.set(qn("w:fill"), fill)
    tcPr.append(node)


def repeat_table_header(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    trPr.append(node)


# ==============================================================================
# Renderizado de jerarquía espacial (nuevo, v8.1)
# ==============================================================================

def _numeral_marker(text: str) -> tuple[str | None, str]:
    """
    Extrae el marcador de numeral y el texto restante.

    Retorna (marcador, resto). Ej: ('1.', 'Proporcione papel...')
    """
    m = re.match(r"^(\d{1,3}[\.)\-–—]\s*)(.*)", text)
    if m:
        return m.group(1).strip(), m.group(2)
    m = re.match(r"^([a-záéíóúñ][\.)]\s*)(.*)", text, re.I)
    if m:
        return m.group(1).strip(), m.group(2)
    return None, text


def _classify_indent_level(indent: float, reference_indeents: list[float]) -> int:
    """
    Clasifica el nivel de sangría comparándolo con referentes previos.

    Niveles:
      0 → sin sangría (numeral principal)
      1 → sangría media (inciso a, b, c)
      2 → sangría profunda (sub-inciso i, ii, 1.1)
    """
    if not reference_indeents:
        return 0
    min_indent = min(reference_indeents)
    max_indent = max(reference_indeents)
    range_size = max(max_indent - min_indent, 1)

    if indent <= min_indent + range_size * 0.3:
        return 0
    elif indent >= max_indent - range_size * 0.3:
        return 2
    else:
        return 1


def render_hierarchical_text(doc, hierarchy: HierarchicalNode,
                              reference_indeents: list[float] | None = None) -> None:
    """
    Renderiza un árbol jerárquico usando estilos nativos de Word.

    - Nivel 0 (numerales) → List Number
    - Nivel 1 (incisos)   → List Bullet  o List Number según contexto
    - Nivel 2 (sub-incisos)→ List Bullet
    - Texto libre          → párrafo normal con indentación manual
    """
    if reference_indeents is None:
        reference_indeents = []

    for level, text, indent in flatten_hierarchy(hierarchy):
        if not text or text == "[ROOT]":
            continue

        # Detectar tipo de marcador
        marker, body = _numeral_marker(text)

        if level == 0 and marker:
            # Numeral principal → List Number
            p = doc.add_paragraph(style="List Number")
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.left_indent = Cm(0.55)
            p.paragraph_format.first_line_indent = Cm(-0.4)
            p.paragraph_format.space_before = Pt(7)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(body)
            fmt(r, 9, True, False, BLACK)
            reference_indeents.append(indent)

        elif level == 1 and marker:
            # Inciso → List Bullet (o List Number si es letra)
            letter = marker[0].lower() if marker else ""
            if letter.isalpha():
                p = doc.add_paragraph(style="List Bullet")
            else:
                p = doc.add_paragraph(style="List Number")
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.left_indent = Cm(0.7 + 0.55 * 1)
            p.paragraph_format.first_line_indent = Cm(-0.4)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.0
            r = p.add_run(body)
            fmt(r, 9, False, True)
            reference_indeents.append(indent)

        elif level >= 2 and marker:
            # Sub-inciso → List Bullet con mayor sangría
            p = doc.add_paragraph(style="List Bullet")
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.left_indent = Cm(0.7 + 0.55 * 2)
            p.paragraph_format.first_line_indent = Cm(-0.4)
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(body)
            fmt(r, 9, False, True)
            reference_indeents.append(indent)

        else:
            # Texto sin marcador → párrafo con indentación basada en X
            actual_indent = _classify_indent_level(indent, reference_indeents)
            indent_cm = 0.55 + actual_indent * 0.55
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.left_indent = Cm(indent_cm)
            p.paragraph_format.first_line_indent = Cm(-0.4)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.line_spacing = 1.0
            r = p.add_run(text)
            fmt(r, 9, False, True)
            reference_indeents.append(indent)


def render_table_block(doc, table_block: TableBlock) -> None:
    """
    Renderiza un TableBlock (matriz de PP-Structure) como tabla nativa DOCX.

    La primera fila se marca como encabezado con w:tblHeader.
    """
    rows_data = table_block.rows
    if not rows_data:
        return

    n_cols = table_block.n_cols
    if n_cols == 0:
        return

    table = doc.add_table(rows=0, cols=n_cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for ri, row_data in enumerate(rows_data):
        cells = table.add_row().cells
        # Asegurar que cada fila tenga exactamente n_cols celdas
        padded_row = row_data[:n_cols] + [""] * max(0, n_cols - len(row_data))
        for ci, cell_text in enumerate(padded_row):
            cells[ci].text = str(cell_text).strip()
            for para in cells[ci].paragraphs:
                para.paragraph_format.space_after = Pt(0)
                for run in para.runs:
                    fmt(run, 7.5, ri == 0)
            if ri == 0:
                set_cell_shading(cells[ci], "DDEBF7")
        if ri == 0:
            repeat_table_header(table.rows[0])


def render_textblock_list(doc, blocks: list[TextBlock]) -> None:
    """
    Renderiza una lista de TextBlock conservando la jerarquía por coordenada X.
    """
    if not blocks:
        return

    # Construir árbol jerárquico
    hierarchy = build_hierarchy_from_blocks(blocks)

    if hierarchy and hierarchy.children:
        render_hierarchical_text(doc, hierarchy)
    else:
        # Fallback: renderizar como texto plano con sangrías
        for tb in blocks:
            p = add_text(doc, tb.text, indent=tb.x0 / 72, space=2)


def build_hierarchy_from_blocks(blocks: list[TextBlock]) -> HierarchicalNode:
    """
    Convierte una lista de TextBlock en un árbol jerárquico.
    Reutiliza la lógica de document_model.build_hierarchy.
    """
    from document_model import build_hierarchy
    return build_hierarchy(blocks)


# ==============================================================================
# Renderizado existente (conservado para compatibilidad)
# ==============================================================================

def configure_styles(doc: Document) -> None:
    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9)
    normal.paragraph_format.space_after = Pt(3)
    for name, size, color in [("FiscalOps Title", 12, BLUE),
                               ("FiscalOps Section", 10, BLUE),
                               ("FiscalOps Response", 9, BLACK)]:
        style = styles[name] if name in styles else styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.color.rgb = color
    styles["FiscalOps Title"].font.bold = True
    styles["FiscalOps Section"].font.bold = True


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = paragraph.add_run("Documento de trabajo confidencial | Página ")
    fmt(r, 8, False, False, GRAY)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    paragraph._p.append(fld)


def annex_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    asset_map = {a.get("asset_id"): a for a in data.get("assets", [])}
    for section in data.get("document", {}).get("sections", []):
        n = section.get("number")
        rid = section.get("requirement_id")
        for block in section.get("blocks", []):
            if block.get("type") == "support_list":
                for item in block.get("items", []):
                    value = str(item).strip()
                    if value and value not in seen:
                        rows.append({
                            "numeral": n, "item": value,
                            "type": "Documento soporte", "source": rid,
                        })
                        seen.add(value)
            elif block.get("type") == "asset":
                a = asset_map.get(block.get("asset_id"))
                if a and a.get("include", True):
                    value = a.get("caption") or a.get("file") or a.get("asset_id")
                    key = "asset:" + str(a.get("asset_id"))
                    if key not in seen:
                        rows.append({
                            "numeral": n, "item": value,
                            "type": "Tabla" if a.get("type") == "table" else "Imagen",
                            "source": a.get("file", ""),
                        })
                        seen.add(key)
    return rows


def add_annex_index(doc, data: dict[str, Any]) -> None:
    entries = annex_entries(data)
    if not entries:
        return
    add_section(doc, "Índice de anexos y elementos soporte")
    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["Numeral", "Tipo", "Anexo o elemento", "Referencia"]
    for i, value in enumerate(headers):
        table.rows[0].cells[i].text = value
        set_cell_shading(table.rows[0].cells[i], "DDEBF7")
    repeat_table_header(table.rows[0])
    for entry in entries:
        cells = table.add_row().cells
        for i, value in enumerate((entry["numeral"], entry["type"], entry["item"], entry["source"])):
            cells[i].text = str(value)
            for para in cells[i].paragraphs:
                para.paragraph_format.space_after = Pt(0)
                for run in para.runs:
                    fmt(run, 7.5, i == 0)


def apply_section_control(doc) -> None:
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text.startswith("Respuesta") or text.endswith("REQUERIMIENTO") or text.endswith("PETITORIOS"):
            paragraph.paragraph_format.keep_with_next = True
        if text.startswith("[DESARROLLAR"):
            paragraph.paragraph_format.keep_together = True


def field_value(data: dict[str, Any], key: str, placeholder: str) -> str:
    field_data = data.get("metadata_validation", {}).get("fields", {}).get(key, {})
    value = str(field_data.get("value", "")).strip()
    if not value or value == "[REVISAR MANUALMENTE]":
        return placeholder
    return value


def replace_tokens(text: str, data: dict[str, Any]) -> str:
    mapping = {
        "[RAZÓN SOCIAL]": field_value(data, "taxpayer_name", "[RAZÓN SOCIAL]"),
        "[RFC]": field_value(data, "rfc", "[RFC]"),
        "[NÚMERO DE OFICIO]": field_value(data, "office", "[NÚMERO DE OFICIO]"),
        "[EXPEDIENTE]": field_value(data, "expedient", "[EXPEDIENTE]"),
        "[NÚMERO DE REFERENCIA]": field_value(data, "reference", "[NÚMERO DE REFERENCIA]"),
        "[NÚMERO DE CONTROL]": field_value(data, "control", "[NÚMERO DE CONTROL]"),
        "[IMPUESTO]": field_value(data, "tax", "[IMPUESTO]"),
        "[PERIODO]": field_value(data, "period", "[PERIODO]"),
        "[MONTO]": field_value(data, "amount", "[MONTO]"),
    }
    for token, value in mapping.items():
        text = text.replace(token, value)
    return text


def add_field_table(doc, data: dict[str, Any]) -> None:
    rows = [
        ("Fecha del escrito", "[FECHA DEL ESCRITO]"),
        ("Razón social", field_value(data, "taxpayer_name", "[RAZÓN SOCIAL]")),
        ("RFC", field_value(data, "rfc", "[RFC]")),
        ("Oficio", field_value(data, "office", "[NÚMERO DE OFICIO]")),
        ("Expediente", field_value(data, "expedient", "[EXPEDIENTE]")),
        ("Número de referencia", field_value(data, "reference", "[NÚMERO DE REFERENCIA]")),
        ("Número de control o seguimiento", field_value(data, "control", "[NÚMERO DE CONTROL]")),
        ("Impuesto", field_value(data, "tax", "[IMPUESTO]")),
        ("Periodo", field_value(data, "period", "[PERIODO]")),
        ("Monto", field_value(data, "amount", "[MONTO]")),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    t.autofit = False
    t.columns[0].width = Cm(5)
    t.columns[1].width = Cm(11)
    for i, (a, b) in enumerate(rows):
        cells = t.add_row().cells
        cells[0].text = a
        cells[1].text = b
        for ci, c in enumerate(cells):
            c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for p in c.paragraphs:
                p.paragraph_format.space_after = Pt(0)
                for r in p.runs:
                    fmt(r, 8.5, ci == 0, False, BLUE if ci == 0 else BLACK)
        if i % 2 == 0:
            for c in cells:
                tcPr = c._tc.get_or_add_tcPr()
                sh = OxmlElement("w:shd")
                sh.set(qn("w:fill"), "F7F9FC")
                tcPr.append(sh)


def add_visual_assets(doc, point: dict[str, Any], data: dict[str, Any],
                      asset_dir: Path) -> None:
    by_id = {a["asset_id"]: a for a in data.get("assets", [])}
    selected = [by_id[x] for x in point.get("asset_ids", []) if x in by_id and by_id[x].get("include", True)]
    if not selected:
        return
    add_label(doc, "Elementos visuales asociados")
    for asset in selected:
        if asset.get("type") == "table" and asset.get("mode") == "editable" and asset.get("rows"):
            rows_data = asset["rows"]
            cols = max(len(r) for r in rows_data)
            table = doc.add_table(rows=0, cols=cols)
            table.style = "Table Grid"
            table.autofit = True
            for ri, row in enumerate(rows_data):
                cells = table.add_row().cells
                for ci in range(cols):
                    cells[ci].text = row[ci] if ci < len(row) else ""
                    for p in cells[ci].paragraphs:
                        p.paragraph_format.space_after = Pt(0)
                        for run in p.runs:
                            fmt(run, 7.5, ri == 0)
            cap = doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = cap.add_run(asset.get("caption", "Tabla del requerimiento"))
            fmt(r, 8, False, True, GRAY)
        else:
            path = asset_dir / asset.get("file", "")
            if path.is_file():
                try:
                    doc.add_picture(str(path), width=Inches(6.15))
                    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                    cap = doc.add_paragraph()
                    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    r = cap.add_run(asset.get("caption", "Elemento visual del requerimiento"))
                    fmt(r, 8, False, True, GRAY)
                except Exception:
                    add_item(doc, "[ELEMENTO VISUAL PENDIENTE DE VALIDACIÓN]", 0, "▣", True)


def response_text(doc, text: str) -> None:
    add_label(doc, "Respuesta")
    if not str(text or "").strip():
        text = "[DESARROLLAR RESPUESTA]"
    p = add_text(doc, str(text), indent=0.25)
    if str(text).strip().startswith("["):
        shade(p, "F2F2F2")


def support_items(doc, items: list[str] | None) -> None:
    if items == []:
        return
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.25)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("Documentación soporte:")
    fmt(r, 9, True)
    for item in (items or ["[ANEXO]"]):
        add_item(doc, str(item), 1, "•", False)


def add_one_asset(doc, asset: dict[str, Any] | None, asset_dir: Path, available_width=None) -> None:
    if not asset or not asset.get("include", True):
        return
    visual_size = asset.get("word_size")
    if asset.get("type") == "table" and asset.get("mode") == "editable" and asset.get("rows"):
        rows_data = asset["rows"]
        cols = max(len(r) for r in rows_data)
        table = doc.add_table(rows=0, cols=cols)
        if "Table Grid" in doc.styles:
            table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        caption = OxmlElement("w:tblCaption")
        caption.set(qn("w:val"), asset["asset_id"])
        table._tbl.tblPr.append(caption)
        if available_width is not None or visual_size in {"small", "wide"}:
            available = available_width
            if available is None:
                section = doc.sections[-1]
                available = section.page_width - section.left_margin - section.right_margin
            table.autofit = False
            cell_width = int(available * (0.62 if visual_size == "small" else 1) / cols)
            for column in table.columns:
                column.width = cell_width
        for ri, row in enumerate(rows_data):
            cells = table.add_row().cells
            if ri == 0:
                repeat_table_header(table.rows[-1])
            for ci in range(cols):
                cells[ci].text = row[ci] if ci < len(row) else ""
                for para in cells[ci].paragraphs:
                    for run in para.runs:
                        fmt(run, 7.5, ri == 0)
    else:
        filename = asset.get("file", "")
        path = asset_dir / filename
        if (filename and Path(filename).name == filename and path.is_file()
                and path.resolve().is_relative_to(asset_dir.resolve())):
            width = Inches(6.15)
            if available_width is not None:
                width = min(width, available_width)
            if asset.get("width") and asset.get("height"):
                width = min(width, Inches(8.5) * asset["width"] / asset["height"])
            box = asset.get("bbox")
            if visual_size != "wide" and box and box[2] > box[0]:
                width = min(width, Pt(box[2] - box[0]))
            if visual_size == "small":
                width *= 0.65
            picture = doc.add_picture(str(path), width=int(width))
            picture._inline.docPr.set("descr", asset["asset_id"])
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap.add_run(asset.get("caption", "Elemento visual"))
    fmt(r, 8, False, True, GRAY)


def render_editor_paragraphs(doc, paragraphs: list[dict[str, Any]], requirement: bool) -> None:
    styles = {"heading": "Heading 2", "subheading": "Heading 3",
              "bullet": "List Bullet", "number": "List Number"}
    alignments = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                  "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}
    fonts = {"Arial", "Calibri", "Georgia", "Times New Roman"}
    list_number_id = None
    previous_kind = None
    for item in paragraphs:
        kind = item.get("kind")
        if kind != previous_kind:
            list_number_id = None
        previous_kind = kind
        if kind == "break":
            doc.add_page_break()
            continue
        style = styles.get(kind)
        para = doc.add_paragraph(style=style if style and style in doc.styles else None)
        if kind in {"number", "bullet"}:
            if list_number_id is None:
                list_number_id = new_list(doc, kind)
            properties = para._p.get_or_add_pPr().get_or_add_numPr()
            properties.get_or_add_ilvl().val = 0
            properties.get_or_add_numId().val = list_number_id
        para.alignment = alignments.get(item.get("align"), WD_ALIGN_PARAGRAPH.LEFT)
        para.paragraph_format.space_after = Pt(4)
        if kind == "quote":
            para.paragraph_format.left_indent = Cm(1)
        elif kind not in styles:
            para.paragraph_format.left_indent = Cm(0.55 if requirement else 0.25)
        for value in item.get("runs", []):
            run = para.add_run(value["text"])
            default_size = 13 if kind == "heading" else 11 if kind == "subheading" else 9
            size = value.get("size", default_size)
            color = value.get("color", "")
            fmt(run, size if type(size) is int and 8 <= size <= 32 else default_size,
                value.get("bold", kind in {"heading", "subheading"}),
                value.get("italic", kind == "quote"),
                RGBColor.from_string(color.upper()) if re.fullmatch(r"[0-9a-fA-F]{6}", color) else BLACK)
            font = value.get("font")
            if font in fonts:
                run.font.name = font
            run.underline = bool(value.get("underline"))
            run.font.strike = bool(value.get("strike"))


def new_list(doc, kind):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.parts.numbering import NumberingPart

    try:
        part = doc.part.part_related_by(RT.NUMBERING)
    except KeyError:
        part = NumberingPart.load(
            PackURI("/word/numbering.xml"),
            Document().part.numbering_part.content_type,
            b'<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
            doc.part.package,
        )
        doc.part.relate_to(part, RT.NUMBERING)
    numbering = part.element
    ids = numbering.xpath("./w:abstractNum/@w:abstractNumId")
    abstract_id = max(map(int, ids), default=-1) + 1
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    for tag, value in (("start", "1"), ("numFmt", "decimal" if kind == "number" else "bullet"),
                       ("lvlText", "%1." if kind == "number" else "•"), ("lvlJc", "left")):
        node = OxmlElement("w:" + tag)
        node.set(qn("w:val"), value)
        level.append(node)
    properties = OxmlElement("w:pPr")
    indent = OxmlElement("w:ind")
    indent.set(qn("w:left"), "720")
    indent.set(qn("w:hanging"), "360")
    properties.append(indent)
    level.append(properties)
    abstract.append(level)
    numbering.insert_element_before(abstract, "w:num", "w:numIdMacAtCleanup")
    return numbering.add_num(abstract_id).numId


def render_requirement(doc, point: dict[str, Any], paragraphs: list[dict[str, Any]] | None = None) -> None:
    """
    Renderiza un requerimiento usando estilos nativos de Word.

    Si el punto contiene bloques espaciales (TextBlock con coordenadas),
    usa render_hierarchical_text. Si no, usa el flujo legacy con
    split_structured_lines.
    """
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.left_indent = Cm(0.55)
    p.paragraph_format.first_line_indent = Cm(-0.4)
    p.paragraph_format.space_before = Pt(7)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(f"{point.get('number', 1)}. Requerimiento de la autoridad")
    fmt(r, 9, True, False, BLACK)

    if paragraphs is not None:
        render_editor_paragraphs(doc, paragraphs, requirement=True)
        return

    # Verificar si hay bloques espaciales (nuevo modelo v8.1)
    spatial_blocks: list[TextBlock] = point.get("_spatial_blocks", [])
    if spatial_blocks:
        render_hierarchical_text(doc, build_hierarchy_from_blocks(spatial_blocks))
        return

    # Flujo legacy: texto plano con split_structured_lines
    for block in split_structured_lines(point.get("text", "")):
        if block["kind"] == "paragraph":
            add_text(doc, block["text"], indent=0.55, italic=True, space=3)
        elif block["kind"] == "subitem":
            add_item(doc, block["text"], 1, block["marker"], True)
        else:
            add_item(doc, block["text"], 1, block["marker"], True)


def render_canonical_sections(doc, data: dict[str, Any], asset_dir: Path, available_width=None) -> None:
    """
    Renderiza las secciones canónicas del documento.

    Soporta tanto el modelo dict heredado como bloques espaciales nuevos.
    """
    ensure_document(data)
    point_map = {p.get("requirement_id"): p for p in data.get("points", [])}
    asset_map = {a.get("asset_id"): a for a in data.get("assets", [])}
    body = doc._element.body
    bookmark_id = max(map(int, body.xpath(".//w:bookmarkStart/@w:id")), default=0)

    for section in data["document"].get("sections", []):
        point = point_map.get(
            section.get("requirement_id"),
            {"number": section.get("number", 1), "text": ""},
        )

        # Verificar si hay bloques espaciales directos en la sección
        spatial_blocks: list[TextBlock] = section.get("_spatial_blocks", [])
        table_blocks: list[TableBlock] = section.get("_table_blocks", [])

        if spatial_blocks or table_blocks:
            # Renderizar bloques espaciales
            for tb in table_blocks:
                render_table_block(doc, tb)
            if spatial_blocks:
                render_hierarchical_text(doc, build_hierarchy_from_blocks(spatial_blocks))
            continue

        # Flujo legacy
        for item in section.get("blocks", []):
            start_index = len(body) - 1
            kind = item.get("type")
            if kind == "requirement_text":
                render_requirement(doc, {**point, "text": item.get("text", "")}, item.get("paragraphs"))
            elif kind == "asset":
                add_one_asset(doc, asset_map.get(item.get("asset_id")), asset_dir, available_width)
            elif kind == "response_text":
                if item.get("paragraphs") is None:
                    response_text(doc, item.get("text", ""))
                else:
                    add_label(doc, "Respuesta")
                    render_editor_paragraphs(doc, item["paragraphs"], requirement=False)
            elif kind == "support_list":
                support_items(doc, item.get("items", []))
            elif kind == "page_break":
                p = doc.add_paragraph()
                p.add_run().add_break(WD_BREAK.PAGE)
            if len(body) - 1 > start_index:
                bookmark_id += 1
                start = OxmlElement("w:bookmarkStart")
                end = OxmlElement("w:bookmarkEnd")
                for node in (start, end):
                    node.set(qn("w:id"), str(bookmark_id))
                start.set(qn("w:name"), block_bookmark(section.get("requirement_id"), item["block_id"]))
                body.insert(start_index, start)
                body.insert(len(body) - 1, end)


def build(data: dict[str, Any], out: str | Path, asset_dir: Any = None, *, export_mode: str | None = None, template: bytes | None = None) -> None:
    """
    Construye el documento Word final a partir del modelo documental.

    Parámetros:
        data:       Workspace completado (contiene 'document', 'points', 'assets', etc.).
        out:        Ruta del archivo DOCX de salida.
        asset_dir:  Directorio de activos visuales (por defecto: padre de out / assets).
    """
    asset_dir = Path(asset_dir) if asset_dir else Path(out).parent / "assets"
    if template is not None:
        doc = load_template(template)
        marker = marker_paragraph(doc)
        body = doc._element.body
        section = doc.sections[-1]
        for node in list(body)[body.index(marker._p) + 1:]:
            if node.tag == qn("w:p") and node.pPr is not None and node.pPr.sectPr is not None:
                section = Section(node.pPr.sectPr, doc.part)
                break
        available = (section.page_width or Inches(8.5)) - (section.left_margin or 0) - (section.right_margin or 0)
        start = len(body) - 1
        if data.get("introduction"):
            add_text(doc, data["introduction"], indent=0.25, italic=True)
        render_canonical_sections(doc, data, asset_dir, available if available > 0 else None)
        inserted = list(body)[start:-1]
        if marker.paragraph_format.page_break_before:
            first = next((p for p in doc.paragraphs if p._p in inserted), None)
            if first is not None:
                first.paragraph_format.page_break_before = True
        for node in inserted:
            marker._p.addprevious(node)
        body.remove(marker._p)
        doc.save(out)
        return
    doc = Document()
    configure_styles(doc)
    sec = doc.sections[0]
    sec.top_margin = Cm(1.8)
    sec.bottom_margin = Cm(1.8)
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9)

    # Encabezado
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = hp.add_run(replace_tokens("[RAZÓN SOCIAL]\nRFC: [RFC]", data))
    fmt(r, 8.5, True, False, BLUE)

    # Pie de página
    fp = sec.footer.paragraphs[0]
    add_page_number(fp)

    # Título principal
    add_title(doc, "Contestación al requerimiento" if export_mode == "reviewed" else "Esqueleto de contestación al requerimiento")
    if export_mode:
        label = "Versión revisada en FiscalOps" if export_mode == "reviewed" else "Borrador de trabajo"
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fmt(para.add_run(label), 8, True, False, GRAY)
        keep(para)

    # Alerta de revisión humana
    review = data.get("human_review", {})
    if review.get("required"):
        p = doc.add_paragraph()
        shade(p, "FFF2CC")
        r = p.add_run(
            "[REVISAR DETECCIÓN OCR] Existen campos críticos pendientes de validación humana."
        )
        fmt(r, 9, True, False, WARN_YELLOW)

    # Tabla de campos
    add_field_table(doc, data)

    # Autoridad y comparecencia
    add_section(doc, "Autoridad y comparecencia")
    add_text(doc, "[AUTORIDAD EMISORA]\n[UNIDAD ADMINISTRATIVA]", bold=True)
    add_text(doc, replace_tokens(
        "Asunto: Se proporciona información y documentación requerida en el Oficio "
        "número [NÚMERO DE OFICIO], respecto de [ASUNTO DEL ACTO ADMINISTRATIVO].",
        data,
    ))
    add_text(doc, replace_tokens(
        "La contribuyente [RAZÓN SOCIAL], con RFC [RFC], comparece por conducto de "
        "su representante legal debidamente acreditado ante esa autoridad. Los datos "
        "personales del representante legal, autorizados, domicilios, correos y "
        "teléfonos se omiten deliberadamente en este documento de trabajo.",
        data,
    ))

    # Manifestaciones
    add_section(doc, "Manifestaciones")
    add_text(doc, "Dentro del plazo aplicable, se proporciona la información y "
              "documentación correspondiente a los puntos requeridos por esa autoridad:")

    # Requerimiento
    add_section(doc, "Requerimiento")
    add_text(doc, data.get("introduction", ""), indent=0.25, italic=True)

    # Secciones canónicas
    render_canonical_sections(doc, data, asset_dir)

    # Índice de anexos
    add_annex_index(doc, data)

    # Petitorios
    add_section(doc, "Petitorios")
    add_text(doc, "Por lo anteriormente expuesto, respetuosamente se solicita a esa H. Administración:")
    for a, b in [
        ("Primero.", "Se tenga por presentado en tiempo y forma el presente escrito y la documentación adjunta."),
        ("Segundo.", "Se tenga por atendido el requerimiento contenido en el oficio de referencia."),
        ("Tercero.", "Se continúe con el trámite correspondiente."),
    ]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.first_line_indent = Cm(-0.6)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(a + " ")
        fmt(r, 9, True)
        r = p.add_run(b)
        fmt(r, 9)

    # Firma
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(12)
    for x, bold in [
        ("A T E N T A M E N T E,", True),
        ("[REPRESENTANTE LEGAL]", True),
        ("Representante Legal", False),
        (field_value(data, "taxpayer_name", "[RAZÓN SOCIAL]"), True),
    ]:
        r = p.add_run(x + "\n")
        fmt(r, 9, bold)

    apply_section_control(doc)
    doc.core_properties.author = ""
    doc.core_properties.last_modified_by = ""
    doc.core_properties.title = "Esqueleto profesional de contestación SAT"
    doc.save(out)
