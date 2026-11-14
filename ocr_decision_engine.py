"""Deterministic OCR routing based on observable PDF characteristics."""
from __future__ import annotations

from typing import Any


DECISION_VERSION = "fiscalops.ocr-decision.v1"


def decide_page(page: dict[str, Any]) -> dict[str, Any]:
    kind = str(page.get("page_type", "EMPTY_OR_UNREADABLE"))
    if kind == "DIGITAL_TEXT":
        action, sources, reason = "NATIVE_ONLY", ["PDF_NATIVE"], "Texto nativo legible; se conserva sin OCR indiscriminado."
    elif kind == "SCANNED_IMAGE":
        action, sources, reason = "PADDLEOCR_FULL_PAGE", ["PADDLE_OCR"], "Página sustentada por imagen; requiere OCR local."
    elif kind == "MIXED_CONTENT":
        action, sources, reason = "NATIVE_PLUS_REGIONS", ["PDF_NATIVE", "PADDLE_OCR"], "Se conserva texto nativo y se reservan regiones visuales para OCR."
    elif kind == "LOW_QUALITY":
        action, sources, reason = "PADDLEOCR_RETRY", ["PDF_NATIVE", "OCR_RETRY"], "La extracción contiene señales de baja calidad."
    else:
        action, sources, reason = "RECOVERY_REQUIRED", ["OCR_RETRY", "MANUAL_CORRECTION"], "No existe contenido confiable; se registra incidencia."
    return {
        "page": int(page.get("page", 0)),
        "page_type": kind,
        "action": action,
        "source_priority": sources,
        "reason": reason,
        "ocr_required": action != "NATIVE_ONLY",
        "full_page_ocr": action in {"PADDLEOCR_FULL_PAGE", "PADDLEOCR_RETRY"},
        "regions_pending": action == "NATIVE_PLUS_REGIONS",
        "human_review_required": action in {"PADDLEOCR_RETRY", "RECOVERY_REQUIRED"},
        "status": "DECIDED",
    }


def decide_document(inspection: dict[str, Any]) -> dict[str, Any]:
    pages = [decide_page(page) for page in inspection.get("pages", [])]
    return {
        "schema_version": DECISION_VERSION,
        "pages": pages,
        "summary": {
            "total_pages": len(pages),
            "native_only": sum(item["action"] == "NATIVE_ONLY" for item in pages),
            "full_page_ocr": sum(item["full_page_ocr"] for item in pages),
            "mixed_regions": sum(item["regions_pending"] for item in pages),
            "review_required": sum(item["human_review_required"] for item in pages),
        },
    }
