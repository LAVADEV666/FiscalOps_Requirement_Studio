from __future__ import annotations

import json
from threading import Event
from pathlib import Path

from reportlab.pdfgen import canvas

from cross_validation import cer, validate_cross_sources, wer
from document_inspector import inspect_pdf
from fiscal_interpreter import deterministic_interpretation
from ocr_decision_engine import decide_document
from ollama_provider import OllamaClient, OllamaConfig


def make_pdf(path: Path) -> None:
    document = canvas.Canvas(str(path), pagesize=(612, 792))
    document.setFont("Helvetica", 10)
    document.drawString(50, 760, "Servicio de Administración Tributaria")
    document.drawString(50, 740, "Número de oficio: 500-01-2026-123")
    document.drawString(50, 720, "R.F.C. ABC010101XX0")
    document.drawString(50, 680, "Se solicita lo siguiente:")
    document.drawString(50, 650, "1. Proporcione la documentación del periodo 2025.")
    document.drawString(50, 620, "2. Aclare el importe de $10,000.00.")
    document.showPage()
    document.showPage()
    document.save()


def test_inspector_covers_every_page_and_decides_recovery(tmp_path):
    pdf = tmp_path / "documento.pdf"
    make_pdf(pdf)
    report = inspect_pdf(pdf)
    assert report["total_pages"] == 2
    assert report["inspected_pages"] == 2
    assert report["coverage"] == 1
    decisions = decide_document(report)
    assert len(decisions["pages"]) == 2
    assert decisions["pages"][0]["page_type"] == "DIGITAL_TEXT"
    assert decisions["pages"][1]["action"] in {"RECOVERY_REQUIRED", "SCANNED_IMAGE", "PADDLEOCR_FULL_PAGE"}


def test_quality_metrics_are_not_claimed_without_reference():
    reconstruction = {"text": "[PÁGINA 1]\nR.F.C. ABC010101XX0", "page_count": 1, "non_empty_pages": 1, "pages": [{"page": 1, "text": "R.F.C. ABC010101XX0", "blocks": []}]}
    data = {"metadata_validation": {"fields": {"rfc": {"value": "ABC010101XX0", "source": "PDF_NATIVE"}}}, "points": []}
    result = validate_cross_sources(reconstruction, data)
    assert result["metrics"]["reference_available"] is False
    assert result["fidelity_claim"] == "NOT_DECLARED_WITHOUT_REFERENCE"
    assert result["critical_fields"]["rfc"]["page"] == 1
    assert cer("hola mundo", "hola mundo") == 0
    assert cer("abc XYZ", "abc") == 0.571429
    assert wer("hola mundo", "hola mundo") == 0


def test_cross_validation_keeps_native_ocr_comparison_and_curp_traceability():
    reconstruction = {
        "text": "[PÁGINA 1]\nRFC ABC010101XX0 CURP GODE561231HDFRRL09",
        "page_count": 1,
        "non_empty_pages": 1,
        "pages": [{
            "page": 1,
            "native_text": "RFC ABC010101XX0 CURP GODE561231HDFRRL09",
            "text": "RFC ABC010101XX0 CURP GODE561231HDFRRL08",
            "blocks": [{"fragment_id": "OCR-1", "text": "RFC ABC010101XX0 CURP GODE561231HDFRRL08", "source": "PADDLE_OCR"}],
            "supplemental_blocks": [],
        }],
    }
    data = {"metadata_validation": {"fields": {"rfc": {"value": "ABC010101XX0", "source": "encabezado"}}}}
    result = validate_cross_sources(reconstruction, data)
    comparison = reconstruction["pages"][0]["source_comparisons"][0]
    assert comparison["kind"] == "NATIVE_VS_OCR"
    assert comparison["native_cer_against_ocr"] > 0
    assert result["critical_tokens"]["curp"] == ["GODE561231HDFRRL09"]
    assert result["critical_fields"]["rfc"]["page"] == 1


def test_interpretation_keeps_traceability_and_does_not_invent():
    result = deterministic_interpretation(
        {"metadata_validation": {"fields": {}}, "points": [{"requirement_id": "REQ-001", "text": "Entregue el contrato.", "page_start": 1, "page_end": 1}]},
        {"text": "[PÁGINA 1]\nEntregue el contrato.", "page_count": 1, "non_empty_pages": 1},
        {"discrepancies": []},
    )
    assert result["obligations"][0]["page_start"] == 1
    assert result["human_review_required"] is True
    assert result["legal_foundations"] == []


def test_ollama_status_uses_local_endpoint_and_never_requires_model():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "qwen2.5:3b"}]}).encode()

    client = OllamaClient(OllamaConfig(enabled=True), opener=lambda request, timeout: Response())
    status = client.status()
    assert status["available"] is True
    assert status["model_available"] is True
    assert status["local_only"] is True


def test_ollama_generation_honors_cancellation_before_request():
    called = False

    def opener(request, timeout):
        nonlocal called
        called = True
        raise AssertionError("No debe abrirse una conexión cancelada")

    client = OllamaClient(OllamaConfig(enabled=True), opener=opener)
    cancel = Event(); cancel.set()
    try:
        client._request("/api/tags", cancel=cancel)
    except RuntimeError as error:
        assert "cancelada" in str(error)
    else:
        raise AssertionError("La operación cancelada debía detenerse")
    assert called is False
