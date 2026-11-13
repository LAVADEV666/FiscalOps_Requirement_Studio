from pathlib import Path
from docx import Document
from document_model import build_document
from word_builder import build, annex_entries
from word_audit import compare_document_to_docx, docx_inventory

def sample():
 d={'introduction':'Introducción del requerimiento','points':[{'number':1,'requirement_id':'REQ-001','text':'Requerimiento profesional completo.','fragment_ids':['F1'],'asset_ids':[],'response_text':'Respuesta profesional completa.','support_items':['ANEXO 1 - Papel de trabajo']}],'assets':[],'metadata_validation':{'fields':{'rfc':{'value':'ABC010101XX0'},'taxpayer_name':{'value':'EMPRESA DEMO'}}}};d['document']=build_document(d);return d

def test_comparison_passes(tmp_path):
 d=sample();out=tmp_path/'out.docx';build(d,out,tmp_path);result=compare_document_to_docx(d,out);assert result['valid'] and len(result['sha256'])==64

def test_annex_index_content(tmp_path):
 d=sample();assert annex_entries(d)[0]['item']=='ANEXO 1 - Papel de trabajo';out=tmp_path/'out.docx';build(d,out,tmp_path);inv=docx_inventory(out);assert 'Índice de anexos y elementos soporte'.upper() in inv['text'].upper();assert inv['tables']>=2

def test_page_break_preserved(tmp_path):
 d=sample();d['document']['sections'][0]['blocks'].insert(1,{'block_id':'PB1','type':'page_break','version':1});out=tmp_path/'out.docx';build(d,out,tmp_path);assert docx_inventory(out)['page_breaks']>=1

def test_comparison_detects_missing(tmp_path):
 d=sample();out=tmp_path/'bad.docx';Document().save(out);result=compare_document_to_docx(d,out);assert not result['valid'] and result['missing']


def test_word_preserves_accepted_list_punctuation(tmp_path):
    data = sample()
    original = "a.Detalle del ajuste.\n\nb. Conservar el texto editado."
    data["document"]["sections"][0]["blocks"][0]["text"] = original
    output = tmp_path / "word.docx"
    build(data, output, tmp_path)
    assert compare_document_to_docx(data, output)["valid"]


def test_word_exports_native_editor_formatting(tmp_path):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from document_model import validate_document

    data = sample()
    response = data["document"]["sections"][0]["blocks"][1]
    response["text"] = "Importe conciliado\n\nPrimer anexo"
    response["paragraphs"] = [
        {"kind": "heading", "align": "center", "runs": [
            {"text": "Importe ", "font": "Georgia", "size": 18, "color": "166658", "bold": True},
            {"text": "conciliado", "italic": True, "underline": True},
        ]},
        {"kind": "number", "runs": [{"text": "Primer anexo"}]},
    ]
    assert validate_document(data["document"], data)["valid"]
    output = tmp_path / "formatted.docx"
    build(data, output, tmp_path)
    doc = Document(output)
    heading = next(p for p in doc.paragraphs if p.text == "Importe conciliado")
    assert heading.style.name == "Heading 2"
    assert heading.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert heading.runs[0].font.name == "Georgia"
    assert heading.runs[0].font.size.pt == 18
    assert str(heading.runs[0].font.color.rgb) == "166658"
    assert heading.runs[0].bold and heading.runs[1].italic and heading.runs[1].underline
    assert next(p for p in doc.paragraphs if p.text == "Primer anexo").style.name == "List Number"
    assert compare_document_to_docx(data, output)["valid"]
    response["text"] = "Texto distinto"
    assert not validate_document(data["document"], data)["valid"]


def test_audit_detects_response_moved_outside_its_block(tmp_path):
    data = sample()
    output = tmp_path / "misplaced.docx"
    build(data, output, tmp_path)
    doc = Document(output)
    requirement = next(p for p in doc.paragraphs if p.text == "Requerimiento profesional completo.")
    response = next(p for p in doc.paragraphs if p.text == "Respuesta profesional completa.")
    requirement._p.addnext(response._p)
    doc.save(output)
    comparison = compare_document_to_docx(data, output)
    assert not comparison["valid"]
    assert any(issue["group"] == "block" and issue["value"] == "REQ-001-RESP" for issue in comparison["missing"])


def test_reviewed_word_does_not_reinsert_empty_annex_placeholder(tmp_path):
    data = sample()
    support = next(b for b in data["document"]["sections"][0]["blocks"] if b["type"] == "support_list")
    support["items"] = []
    output = tmp_path / "reviewed.docx"
    build(data, output, tmp_path, export_mode="reviewed")
    assert "[ANEXO]" not in docx_inventory(output)["text"]
    assert compare_document_to_docx(data, output)["valid"]
