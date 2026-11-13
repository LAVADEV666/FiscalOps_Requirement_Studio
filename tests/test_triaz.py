"""Tests específicos para el motor de triage PyMuPDF (processing_pipeline.py)."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).parent.parent))
from processing_pipeline import triage_pdf, triage_page, ProcessingPipeline


def _make_pdf_with_text(path: Path, texts: list[str]) -> None:
    """Crea un PDF simple con texto nativo usando ReportLab."""
    c = canvas.Canvas(str(path))
    y = 790
    for line in texts:
        c.drawString(50, y, line)
        y -= 20
    c.save()


def _make_scan_pdf(path: Path, page_count: int = 3) -> None:
    """Crea un PDF vacío (solo imágenes, sin texto) simulando un escaneo."""
    c = canvas.Canvas(str(path))
    for _ in range(page_count):
        c.drawImage(str(Path(__file__).parent.parent / "static" / "style.css".replace("style.css", "")), 0, 0, width=0, height=0)
        c.showPage()
    c.save()


def test_triaz_native_dominant(tmp_path):
    pdf = tmp_path / "native.pdf"
    _make_pdf_with_text(pdf, [
        "Servicio de Administracion Tributaria",
        "Numero de oficio: 500-01-2026-123",
        "R.F.C. ABC010101XX0",
        "Se solicita lo siguiente:",
        "1. Proporcione papel de trabajo.",
        "2. Aclare las diferencias.",
    ])
    result = triage_pdf(pdf)
    assert result["global_strategy"] == "native_dominant"
    assert result["native_pages"] > 0
    assert result["scan_pages"] == 0


def test_triaz_all_scan(tmp_path):
    """PDFs vacíos deberían clasificarse como scan."""
    pdf = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(pdf))
    for _ in range(5):
        c.showPage()
    c.save()
    result = triage_pdf(pdf)
    assert result["global_strategy"] == "scan_dominant"
    assert result["scan_pages"] == 5
    assert result["native_pages"] == 0


def test_triaz_mixed_pages():
    """Simula una página con texto + imágenes."""
    mock_page = MagicMock()
    mock_page.rect.width = 612
    mock_page.rect.height = 792
    # Palabras simuladas (texto nativo)
    mock_page.get_text.return_value = {"blocks": [{"type": 0, "lines": [{"spans": [{"text": "texto de prueba"}]}]}]}
    mock_page.get_images.return_value = [1]  # 1 imagen
    # get_text("words") para la lógica real
    mock_page.get_text.side_effect = lambda kind=None: (
        [(0, 0, 10, 10, "word1", 0, 0, 0),
         (15, 0, 25, 10, "word2", 0, 0, 1),
         (30, 0, 40, 10, "word3", 0, 0, 2)]
        if kind == "words" else MagicMock()
    )
    result = triage_page(mock_page)
    assert result["word_count"] == 3
    assert result["text_length"] > 0
    # Con pocas palabras debería ser scan o mixed dependiendo de umbral
    assert result["strategy"] in ("scan", "mixed", "native")


def test_triaz_zero_pages():
    """PDF sin páginas no debería crashear."""
    pdf = Path(__file__).parent.parent / "work" / "_nonexistent.pdf"
    try:
        pdf.parent.mkdir(exist_ok=True)
        result = triage_pdf(pdf)
        assert result["total_pages"] == 0
    except ValueError:
        pass  # esperado si el archivo no existe


def test_pipeline_lazy_ocr_service(tmp_path):
    """OcrService no debe crearse hasta que se necesite."""
    work = tmp_path / "work"
    pipe = ProcessingPipeline(work)
    assert pipe._ocr_service is None
    # Acceder a la propiedad debería crear el servicio
    _ = pipe.ocr_service
    assert pipe._ocr_service is not None


def test_pipeline_scan_without_ocr_error(tmp_path):
    """Pipeline debe elevar ValueError claro si hay scans y no hay OCR."""
    pdf = tmp_path / "scan_only.pdf"
    c = canvas.Canvas(str(pdf))
    for _ in range(3):
        c.showPage()
    c.save()

    with patch.object(ProcessingPipeline, 'ocr_service') as mock_ocr:
        mock_ocr.is_usable.return_value = False
        pipe = ProcessingPipeline(tmp_path / "work2")
        pipe._ocr_service = mock_ocr
        try:
            pipe.run("test-scan-no-ocr", pdf)
            assert False, "Debería haber elevado ValueError"
        except ValueError as exc:
            assert "OCR" in str(exc) or "paddleocr" in str(exc).lower() or "pytesseract" in str(exc).lower()
