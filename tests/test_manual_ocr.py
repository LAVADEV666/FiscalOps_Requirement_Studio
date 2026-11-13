import fitz
import pytest
from PIL import Image

from audit_engine import render_pages
from document_model import ensure_document
from manual_ocr import Region, apply_reading, read_regions, validate_regions
from persistence import load_json_recover
from processing_pipeline import ProcessingPipeline


def test_regions_match_rotated_pdf_and_render_original_crop(tmp_path):
    pdf = tmp_path / "source.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=400)
        page.insert_text((25, 55), "Zona superior elegida")
        page.insert_text((25, 270), "Texto fuera del recorte")
        page.set_rotation(90)
        rect = fitz.Rect(10, 35, 170, 70) * page.rotation_matrix
        region = Region(page=1, rect=(rect.x1 / page.rect.width, rect.y1 / page.rect.height,
                                      rect.x0 / page.rect.width, rect.y0 / page.rect.height))
        doc.save(pdf)
    render_pages(pdf, tmp_path / "pages")
    validate_regions(tmp_path, [region], 1)
    native = read_regions(tmp_path, [region], None)[0]
    assert native["text"] == "Zona superior elegida"
    assert native["method"] == "native"

    class InspectCrop:
        def read_region(self, path):
            with Image.open(path) as img:
                assert img.width > 800 and 180 < img.height < 210
                assert img.getextrema()[0][0] < 80
            return {"text": "Recorte comprobado", "confidence": .95}

    forced = read_regions(tmp_path, [region], InspectCrop(), force_ocr=True, rotation=270)[0]
    assert forced["text"] == "Recorte comprobado"
    assert forced["method"] == "paddleocr"
    with pytest.raises(ValueError, match="más grande"):
        validate_regions(tmp_path, [Region(page=1, rect=(0, 0, 0, .5))], 1)


def test_apply_updates_only_selected_numeral_and_retains_answers():
    data = {"points": [
        {"number": 1, "requirement_id": "REQ-001", "text": "Texto inicial", "original_text": "Texto inicial",
         "response_text": "Respuesta redactada", "page_start": 1, "page_end": 1},
        {"number": 2, "requirement_id": "REQ-002", "text": "Otro numeral", "page_start": 3, "page_end": 3},
    ], "assets": [{"asset_id": "EXISTENTE", "caption": "Activo previo"}],
        "metadata_validation": {"fields": {"rfc": {"value": "ABC010101AB1"}}}}
    ensure_document(data)
    regions = [Region(page=2, rect=(.1, .2, .9, .4)), Region(page=1, rect=(.1, .5, .9, .7))]
    assert apply_reading(data, regions, "REQ-001", "Texto revisado") == "REQ-001"
    first, second = data["points"]
    assert (first["text"], first["original_text"], first["response_text"], first["page_end"]) == (
        "Texto revisado", "Texto inicial", "Respuesta redactada", 2)
    assert second["text"] == "Otro numeral"
    assert data["assets"][0]["asset_id"] == "EXISTENTE"
    assert data["metadata_validation"]["fields"]["rfc"]["value"] == "ABC010101AB1"
    assert data["document"]["sections"][0]["blocks"][0]["source_fragment_ids"] == first["fragment_ids"]
    assert data["audit_log"][-1]["before"] == "Texto inicial"
    assert apply_reading(data, regions, None, "Numeral omitido recuperado") == "REQ-003"
    assert [section["number"] for section in data["document"]["sections"]] == [1, 2, 3]


def test_failed_initial_read_keeps_pdf_available_for_manual_recovery(tmp_path):
    pdf = tmp_path / "unreadable.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(pdf)

    class MissingEngine:
        def is_usable(self):
            return False

    work = tmp_path / "work"
    result = ProcessingPipeline(work, ocr_service=MissingEngine()).run("test", pdf, recover_ocr=True)
    folder = work / result["session_id"]
    saved = load_json_recover(folder / "workspace.json")
    assert saved["diagnostics"]["strategy"] == "manual_ocr"
    assert saved["points"] == []
    assert (folder / "source.pdf").is_file()
    assert (folder / "pages" / "page-1.png").is_file()
    assert "INSTALAR_OCR" in saved["ocr_diagnostics"]["pages"][0]["error"]
