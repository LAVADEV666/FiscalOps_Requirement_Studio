from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import re
import tempfile
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError, tostring

from enterprise_store import RFC_RE
from persistence import workspace_lock, atomic_json, load_json_recover, atomic_replace

MARKER = "{{REQUERIMIENTO}}"
MAX_TEMPLATE_BYTES = 20 * 1024**2
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEMPLATE_SLOTS = {
    "primer": "1er requerimiento",
    "segundo": "2do requerimiento",
}
LEGACY_ID = re.compile(r"[a-f0-9]{32}")
ALIGNMENT = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
FONT_TOGGLES = ("bold", "italic", "underline")


class TemplateSlotOccupied(ValueError):
    pass


def template_rfc(value: str) -> str:
    rfc = value.strip().upper()
    if not RFC_RE.fullmatch(rfc):
        raise ValueError("Escribe un RFC de 12 o 13 caracteres.")
    return rfc


def marker_paragraph(doc, *, add_missing=False):
    body = doc._element.body
    matches = [Paragraph(node, doc) for node in body.iter(qn("w:p"))
               if MARKER in Paragraph(node, doc).text]
    if not matches and add_missing:
        marker = doc.add_paragraph(MARKER)
        shade_marker(marker)
        return marker
    if len(matches) != 1 or matches[0]._p.getparent() is not body or matches[0].text.strip() != MARKER:
        raise ValueError(f"Coloca {MARKER} una sola vez, en un párrafo independiente del cuerpo del documento.")
    marker = matches[0]
    if marker._p.xpath("./w:pPr/w:sectPr | .//w:drawing | .//w:object | .//w:fldChar | .//w:fldSimple | .//w:hyperlink | .//w:br[@w:type='page']"):
        raise ValueError(f"Usa un párrafo de texto independiente para {MARKER}, separado de imágenes, campos y saltos.")
    return marker


def shade_marker(paragraph):
    properties = paragraph._p.get_or_add_pPr()
    if properties.find(qn("w:shd")) is None:
        shade = OxmlElement("w:shd")
        shade.set(qn("w:val"), "clear")
        shade.set(qn("w:fill"), "F3EAFA")
        properties.insert_element_before(shade, "w:tabs", "w:suppressAutoHyphens", "w:kinsoku",
                                         "w:wordWrap", "w:overflowPunct", "w:topLinePunct",
                                         "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
                                         "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
                                         "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                                         "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
                                         "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def load_template(content: bytes, *, allow_export=False):
    if not content or len(content) > MAX_TEMPLATE_BYTES:
        raise ValueError("La plantilla DOCX debe ocupar entre 1 byte y 20 MB.")
    try:
        with ZipFile(BytesIO(content)) as archive:
            files = archive.infolist()
            names = {file.filename.casefold() for file in files}
            if len(names) != len(files) or len(files) > 3000 or sum(file.file_size for file in files) > 100 * 1024**2:
                raise ValueError("El DOCX contiene demasiados recursos, archivos duplicados o supera el límite descomprimido.")
            if any("vbaproject" in name or name.startswith("word/activex/") for name in names):
                raise ValueError("Guarda la plantilla como DOCX sin macros ni controles ActiveX.")
        doc = Document(BytesIO(content))
    except (BadZipFile, KeyError, XMLSyntaxError, OSError) as exc:
        raise ValueError("No se pudo abrir el archivo como DOCX de Word.") from exc
    if doc.part.content_type != DOCX_MIME + ".main+xml":
        raise ValueError("Importa un documento de Word en formato DOCX.")
    doc._element.body.get_or_add_sectPr()
    if not allow_export and doc.settings.element.xpath("./w:documentProtection[@w:enforcement='1' or @w:enforcement='true' or @w:enforcement='on']"):
        raise ValueError("Quita la protección de edición en Word antes de importar la plantilla.")
    if not allow_export and any(name.startswith("FO_") for name in doc._element.body.xpath(".//w:bookmarkStart/@w:name")):
        raise ValueError("Importa el Word base de la plantilla, sin marcadores de una exportación anterior de FiscalOps.")
    return doc


def template_example() -> bytes:
    doc = Document()
    for style_name in ("Title", "Heading 1"):
        style = doc.styles[style_name]
        style.font.color.rgb = RGBColor(0, 0, 0)
        for border in style.element.xpath("./w:pPr/w:pBdr"):
            border.getparent().remove(border)
    doc.sections[0].header.paragraphs[0].text = "Encabezado de la empresa"
    doc.add_paragraph("Contestación al requerimiento", style="Title")
    doc.add_paragraph("Portada y datos de la empresa")
    shade_marker(doc.add_paragraph(MARKER))
    doc.add_paragraph("Cierre y firma", style="Heading 1")
    doc.add_paragraph("Nombre y cargo de quien firma")
    doc.sections[0].footer.paragraphs[0].text = "Pie de página de la empresa"
    return as_bytes(doc)


def as_bytes(doc) -> bytes:
    result = BytesIO()
    doc.save(result)
    return result.getvalue()


def body_blocks(doc, marker):
    return [node for node in doc._element.body if node is not marker._p and node.tag != qn("w:sectPr")]


def editable_fields(doc, marker):
    def editable(paragraph):
        if paragraph._p.xpath("./w:pPr/w:sectPr"):
            return False
        if any(node.tag not in {qn("w:pPr"), qn("w:r")} for node in paragraph._p):
            return False
        if any(node.tag not in {qn("w:rPr"), qn("w:t")} for run in paragraph.runs for node in run._r):
            return False
        return len({tostring(run._r.rPr) if run._r.rPr is not None else b"" for run in paragraph.runs}) <= 1

    body = doc._element.body
    position = body.index(marker._p)
    for index, node in enumerate(body.iter(qn("w:p"))):
        paragraph = Paragraph(node, doc)
        if paragraph._p is not marker._p and editable(paragraph):
            top = node
            while top.getparent() is not body:
                top = top.getparent()
            group = "Portada e inicio" if body.index(top) < position else "Cierre"
            yield f"body:{index}", group, paragraph
    for key, rel in doc.part.rels.items():
        if not rel.is_external and rel.reltype in {RT.HEADER, RT.FOOTER}:
            group = "Encabezado" if rel.reltype == RT.HEADER else "Pie de página"
            for index, node in enumerate(rel.target_part.element.iter(qn("w:p"))):
                paragraph = Paragraph(node, rel.target_part)
                if editable(paragraph):
                    yield f"{key}:{index}", group, paragraph


def paragraph_format(paragraph):
    styles = []
    style = paragraph.style
    while style is not None and style.style_id not in {item.style_id for item in styles}:
        styles.append(style)
        style = style.base_style
    run = next(iter(paragraph.runs), None)
    fonts = ([run.font] if run is not None else []) + [style.font for style in styles]
    values = {}
    for key in (*FONT_TOGGLES, "size"):
        value = next((getattr(font, key) for font in fonts if getattr(font, key) is not None), None)
        values[key] = (value.pt if value is not None else 11) if key == "size" else bool(value)
    align = paragraph.alignment
    if align is None:
        align = next((style.paragraph_format.alignment for style in styles
                      if style.paragraph_format.alignment is not None), None)
    values["align"] = next((key for key, value in ALIGNMENT.items() if value == align), "left")
    return values


class TemplateStore:
    def __init__(self, root: Path):
        self.root = root

    def create(self, rfc, template_id, style="letter"):
        if style not in {"blank", "letter"}:
            raise ValueError("Selecciona una plantilla en blanco o una carta.")
        if style == "letter":
            content = template_example()
        else:
            doc = Document()
            doc.sections[0].header.paragraphs[0].text = ""
            doc.add_paragraph("")
            shade_marker(doc.add_paragraph(MARKER))
            doc.add_paragraph("")
            content = as_bytes(doc)
        return self.save(rfc, template_id, content)

    def profile_path(self, rfc):
        return self.path(rfc, "primer").parent / "identity.json"

    def profile(self, rfc):
        path = self.profile_path(rfc)
        return load_json_recover(path) if path.exists() else {"rfc": template_rfc(rfc), "icon": "building", "color": "#6b4389"}

    def set_profile(self, rfc, icon, color):
        if icon not in {"building", "briefcase", "factory", "shop", "bank", "leaf", "star", "document"} or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Selecciona un icono y un color válidos.")
        value = {"rfc": template_rfc(rfc), "icon": icon, "color": color}
        path = self.profile_path(rfc)
        with workspace_lock(path):
            atomic_json(path, value)
        return value

    def library(self):
        result = []
        if not self.root.exists():
            return result
        for folder in sorted(self.root.iterdir()):
            if folder.is_dir() and RFC_RE.fullmatch(folder.name):
                slots = self.list(folder.name)
                if any(item["configured"] for item in slots) or self.profile_path(folder.name).exists():
                    result.append({**self.profile(folder.name), "templates": slots})
        return result

    def path(self, rfc: str, template_id: str, *, legacy=False) -> Path:
        if legacy:
            if not LEGACY_ID.fullmatch(template_id):
                raise ValueError("Identificador de plantilla anterior inválido.")
        elif template_id not in TEMPLATE_SLOTS:
            raise ValueError("Selecciona 1er requerimiento o 2do requerimiento.")
        path = self.root / template_rfc(rfc) / f"{template_id}.docx"
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Ruta de plantilla inválida.")
        return path

    def list(self, rfc: str):
        return [{"id": slot, "name": name, "configured": self.path(rfc, slot).is_file()}
                for slot, name in TEMPLATE_SLOTS.items()]

    def legacy(self, rfc: str):
        result = []
        for path in sorted((self.root / template_rfc(rfc)).glob("*.docx")):
            if not LEGACY_ID.fullmatch(path.stem):
                continue
            try:
                name = load_template(self.read_legacy(rfc, path.stem)).core_properties.title
            except (OSError, ValueError):
                name = ""
            result.append({"id": path.stem, "name": name or path.name})
        return sorted(result, key=lambda item: item["name"].casefold())

    def read_legacy(self, rfc: str, template_id: str) -> bytes:
        return self.path(rfc, template_id, legacy=True).read_bytes()

    def read(self, rfc: str, template_id: str) -> bytes:
        return self.path(rfc, template_id).read_bytes()

    def details(self, rfc: str, template_id: str):
        content = self.read(rfc, template_id)
        doc = load_template(content)
        marker = marker_paragraph(doc)
        blocks = body_blocks(doc, marker)
        options = []
        for node in blocks:
            text = " ".join("".join(part.text or "" for part in node.iter(qn("w:t"))).split())
            options.append(text[:90] or ("Tabla" if node.tag == qn("w:tbl") else "Bloque o salto de página"))
        fields = list(editable_fields(doc, marker))
        by_node = {p._p: key for key, _, p in fields}
        layout = []
        for node in blocks:
            kind = "table" if node.tag == qn("w:tbl") else "paragraph"
            if any(part.tag in {qn("w:drawing"), qn("w:pict"), qn("w:object")} for part in node.iter()):
                kind = "visual"
            layout.append({"kind": kind, "fields": [by_node[p] for p in node.iter(qn("w:p")) if p in by_node]})
        return {"id": template_id, "name": TEMPLATE_SLOTS[template_id], "rfc": template_rfc(rfc),
                "revision": hashlib.sha256(content).hexdigest(),
                "position": sum(doc._element.body.index(node) < doc._element.body.index(marker._p) for node in blocks),
                "blocks": options, "layout": layout,
                "ocr_frame": bool(marker._p.xpath("./w:pPr/w:pBdr")),
                "fields": [{"id": key, "group": group, "text": p.text, "format": paragraph_format(p)}
                           for key, group, p in fields]}

    def save(self, rfc: str, template_id: str, content: bytes, revision=None):
        path = self.path(rfc, template_id)
        doc = load_template(content)
        marker_paragraph(doc, add_missing=True)
        with workspace_lock(path):
            if revision is not None:
                self.check_revision(path, revision)
            elif path.exists():
                raise TemplateSlotOccupied("Este tipo ya tiene una plantilla. Ábrela para sustituir el DOCX.")
            self.write(path, TEMPLATE_SLOTS[template_id], doc)
            return self.details(rfc, template_id)

    def edit(self, rfc, template_id, revision, position, fields, formatting=None, ocr_frame=None):
        path = self.path(rfc, template_id)
        with workspace_lock(path):
            doc = load_template(self.check_revision(path, revision))
            marker = marker_paragraph(doc)
            available = {key: p for key, _, p in editable_fields(doc, marker)}
            for key, text in fields.items():
                if key not in available or MARKER in text or len(text) > 12000 or any(ord(c) < 32 for c in text):
                    raise ValueError("Uno de los textos de la plantilla no es válido.")
                paragraph = available[key]
                if paragraph.text != text:
                    first = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
                    first.text = text
                    for run in paragraph.runs[1:]:
                        run.text = ""
            for key, changes in (formatting or {}).items():
                if key not in available:
                    raise ValueError("Selecciona un párrafo editable para aplicar formato.")
                paragraph = available[key]
                if "align" in changes:
                    paragraph.alignment = ALIGNMENT[changes["align"]]
                font_changes = changes.keys() - {"align"}
                if font_changes:
                    for run in paragraph.runs or [paragraph.add_run()]:
                        for prop in font_changes:
                            setattr(run.font, prop, Pt(changes[prop]) if prop == "size" else changes[prop])
            blocks = body_blocks(doc, marker)
            if not 0 <= position <= len(blocks):
                raise ValueError("Selecciona una posición válida para el requerimiento.")
            shade_marker(marker)
            if ocr_frame is not None:
                properties = marker._p.get_or_add_pPr()
                for border in properties.findall(qn("w:pBdr")):
                    properties.remove(border)
                if ocr_frame:
                    borders = OxmlElement("w:pBdr")
                    for side in ("top", "left", "bottom", "right"):
                        border = OxmlElement("w:" + side)
                        for key, value in {"val": "single", "sz": "8", "space": "8", "color": "9870B9"}.items():
                            border.set(qn("w:" + key), value)
                        borders.append(border)
                    properties.insert_element_before(borders, "w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc", "w:sectPr")
            body = doc._element.body
            body.remove(marker._p)
            if position < len(blocks):
                blocks[position].addprevious(marker._p)
            else:
                body.insert_element_before(marker._p, "w:sectPr")
            self.write(path, TEMPLATE_SLOTS[template_id], doc)
            return self.details(rfc, template_id)

    @staticmethod
    def check_revision(path, revision):
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != revision:
            raise ValueError("La plantilla cambió en otra sesión. Vuelve a abrirla antes de guardar.")
        return content

    @staticmethod
    def write(path, name, doc):
        doc.core_properties.title = name
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            doc.save(temporary)
            atomic_replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
