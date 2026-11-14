from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas

from document_inspector import inspect_pdf
from mixed_region_ocr import run_mixed_region_ocr
from processing_pipeline import ProcessingPipeline


class FakeOCR:
    def __init__(self):
        self.calls = []

    def is_usable(self):
        return True

    def run(self, image_path, force=False, psm=None):
        self.calls.append(Path(image_path).name)
        return {"text": "Texto visual 2025", "text_blocks": [{"block_id": "B1", "text": "Texto visual 2025", "bbox": [0, 0, 80, 20], "confidence": 0.96, "requires_review": False}]}


def test_mixed_pages_ocr_only_embedded_visual_regions(tmp_path):
    pdf = tmp_path / "mixed.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(40, 760, "Texto nativo que debe permanecer canónico")
    c.drawImage(str(Path(__file__).parents[1] / "static" / "ssgt-symbol.png"), 40, 500, width=180, height=180)
    c.save()
    inspection = inspect_pdf(pdf)
    assert inspection["pages"][0]["page_type"] == "MIXED_CONTENT"
    result = run_mixed_region_ocr(pdf, tmp_path / "regions", inspection, FakeOCR(), min_area_ratio=0.001)
    assert result["summary"]["processed"] == 1
    assert result["regions"][0]["source"] == "PADDLE_OCR"


def test_pipeline_keeps_short_native_text_and_ocr_only_mixed_region(tmp_path):
    pdf = tmp_path / "mixed-pipeline.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(40, 760, "Servicio de Administración Tributaria. Número de oficio: 500-01-2026-001. Se solicita: 1. Entregue contrato.")
    c.drawImage(str(Path(__file__).parents[1] / "static" / "ssgt-symbol.png"), 40, 500, width=180, height=180)
    c.save()
    fake = FakeOCR()
    result = ProcessingPipeline(tmp_path / "work", ocr_service=fake).run("mixed", pdf, recover_ocr=True)
    import json
    data = json.loads((tmp_path / "work" / result["session_id"] / "workspace.json").read_text(encoding="utf-8"))
    page = data["reconstruction"]["pages"][0]
    assert page["page_type"] == "MIXED_CONTENT"
    assert "PDF_NATIVE" in page["source_priority"]
    assert page["supplemental_blocks"]
    assert fake.calls and len(fake.calls) == 1
