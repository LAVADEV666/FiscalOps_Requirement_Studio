from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas

from document_inspector import inspect_pdf
from mixed_region_ocr import run_mixed_region_ocr


class FakeOCR:
    def is_usable(self):
        return True

    def run(self, image_path, force=False, psm=None):
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
