from io import BytesIO

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from PIL import Image

from document_model import ensure_document
from template_store import MARKER, TemplateSlotOccupied, TemplateStore, as_bytes, load_template, template_example
from word_audit import compare_document_to_docx
from word_builder import build


def test_import_edit_replace_and_isolate_templates_by_rfc(tmp_path):
    store = TemplateStore(tmp_path)
    original = Document()
    original.add_paragraph("Portada")
    original.add_paragraph("Firma original").runs[0].bold = True
    original.sections[0].header.paragraphs[0].add_run("Encabezado original")
    item = store.save("abc010101ab1", "primer", as_bytes(original))
    assert item["position"] == 2
    assert not any(slot["configured"] for slot in store.list("DEF010101CD2"))
    with pytest.raises(FileNotFoundError):
        store.read("DEF010101CD2", item["id"])
    updates = {field["id"]: "Firma editada" if field["text"].startswith("Firma") else "Encabezado editado"
               for field in item["fields"] if field["text"] != "Portada"}
    saved = store.edit(item["rfc"], item["id"], item["revision"], 1, updates)
    doc = load_template(store.read(item["rfc"], item["id"]))
    assert [p.text for p in doc.paragraphs] == ["Portada", MARKER, "Firma editada"]
    assert doc.paragraphs[2].runs[0].bold
    assert doc.sections[0].header.paragraphs[0].text == "Encabezado editado"
    with pytest.raises(ValueError, match="otra sesión"):
        store.edit(item["rfc"], item["id"], item["revision"], 0, {})
    replaced = store.save(item["rfc"], item["id"], template_example(), saved["revision"])
    assert replaced["id"] == item["id"]


def test_only_two_named_slots_and_legacy_files_stay_downloadable(tmp_path):
    store = TemplateStore(tmp_path)
    rfc = "ABC010101AB1"
    content = template_example()
    assert store.list(rfc) == [
        {"id": "primer", "name": "1er requerimiento", "configured": False},
        {"id": "segundo", "name": "2do requerimiento", "configured": False},
    ]
    store.save(rfc, "segundo", content)
    with pytest.raises(TemplateSlotOccupied, match="ya tiene una plantilla"):
        store.save(rfc, "segundo", content)
    legacy_id = "a" * 32
    legacy = load_template(content)
    legacy.core_properties.title = "Formato anterior"
    (tmp_path / rfc / f"{legacy_id}.docx").write_bytes(as_bytes(legacy))
    assert store.legacy(rfc) == [{"id": legacy_id, "name": "Formato anterior"}]
    with pytest.raises(ValueError, match="2do requerimiento"):
        store.read(rfc, legacy_id)
    assert store.save(rfc, "primer", store.read_legacy(rfc, legacy_id))["name"] == "1er requerimiento"
    with pytest.raises(ValueError, match="2do requerimiento"):
        store.save(rfc, "tercer", content)
    assert [slot["id"] for slot in store.list(rfc) if slot["configured"]] == ["primer", "segundo"]
    assert load_template(store.read_legacy(rfc, legacy_id)).core_properties.title == "Formato anterior"


def test_editor_moves_marker_and_saves_format_in_original_docx(tmp_path):
    store = TemplateStore(tmp_path)
    source = Document(BytesIO(template_example()))
    mixed = source.add_paragraph("Texto ")
    mixed.add_run("con formato").italic = True
    item = store.save("ABC010101AB1", "primer", as_bytes(source))
    title_id = item["layout"][0]["fields"][0]
    assert item["layout"][-1]["fields"] == []
    store.edit(item["rfc"], item["id"], item["revision"], 1, {title_id: "Portada editada"},
               {title_id: {"bold": True, "align": "center", "size": 24}})
    content = store.read(item["rfc"], item["id"])
    edited = load_template(content)
    title = edited.paragraphs[0]
    assert title.text == "Portada editada"
    assert title.runs[0].bold and title.runs[0].font.size.pt == 24
    assert title.alignment.name == "CENTER"
    assert edited.paragraphs[1].text == MARKER
    assert edited.paragraphs[1]._p.xpath("./w:pPr/w:shd/@w:fill") == ["F3EAFA"]
    assert edited.paragraphs[-1].runs[1].italic
    assert edited.sections[0].header.paragraphs[0].text == "Encabezado de la empresa"
    result = tmp_path / "editor.docx"
    build({"points": [{"number": 1, "text": "Numeral editable."}]}, result, template=content)
    paragraphs = [paragraph.text for paragraph in Document(result).paragraphs]
    assert paragraphs.index("Portada editada") < paragraphs.index("Numeral editable.") < paragraphs.index("Portada y datos de la empresa")
    assert MARKER not in paragraphs


def test_word_inserts_editable_content_without_rebuilding_template(tmp_path):
    source = Document(BytesIO(template_example()))
    for key, relation in list(source.part.rels.items()):
        if relation.reltype == RT.NUMBERING:
            source.part.drop_rel(key)
    source.sections[0].header.paragraphs[0].runs[0].italic = True
    source.sections[0].footer.paragraphs[0].runs[0].bold = True
    image = tmp_path / "logo.png"
    Image.new("RGB", (20, 20), "purple").save(image)
    source.paragraphs[1].add_run().add_picture(str(image))
    table = source.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Tabla del cierre"
    data = {"points": [{"number": 1, "requirement_id": "REQ-001", "text": "Texto detectado del requerimiento.",
                        "asset_ids": ["table"]}], "assets": [{"asset_id": "table", "type": "table", "mode": "editable",
                                                               "rows": [["Tabla OCR"], ["Importe"]]}]}
    doc = ensure_document(data)
    response = doc["sections"][0]["blocks"][2]
    response.update(text="Respuesta editable.", paragraphs=[{"kind": "number", "runs": [{"text": "Respuesta editable."}]}])
    output = tmp_path / "result.docx"
    build(data, output, template=as_bytes(source))
    result = Document(output)
    paragraphs = [p.text for p in result.paragraphs]
    assert paragraphs.index("Portada y datos de la empresa") < paragraphs.index("Texto detectado del requerimiento.") < paragraphs.index("Cierre y firma")
    assert MARKER not in paragraphs
    assert result.sections[0].header.paragraphs[0].runs[0].italic
    assert result.sections[0].footer.paragraphs[0].runs[0].bold
    assert len(result.inline_shapes) == 1
    assert [t.cell(0, 0).text for t in result.tables] == ["Tabla OCR", "Tabla del cierre"]
    response = next(p for p in result.paragraphs if p.text == "Respuesta editable.")
    assert response._p.xpath("./w:pPr/w:numPr")
    assert compare_document_to_docx(data, output)["valid"]


def test_rejects_marker_inside_table_or_repeated(tmp_path):
    store = TemplateStore(tmp_path)
    doc = Document()
    doc.add_table(rows=1, cols=1).cell(0, 0).text = MARKER
    with pytest.raises(ValueError, match="párrafo independiente"):
        store.save("ABC010101AB1", "primer", as_bytes(doc))
    doc = Document()
    doc.add_paragraph(MARKER)
    doc.add_paragraph(MARKER)
    with pytest.raises(ValueError, match="una sola vez"):
        store.save("ABC010101AB1", "primer", as_bytes(doc))
