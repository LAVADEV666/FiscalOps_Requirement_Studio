"""Inspection of every PDF page before extraction.

The inspector is intentionally deterministic.  It never asks an LLM to decide
whether a page contains text and it does not alter the source PDF.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import fitz


INSPECTOR_VERSION = "fiscalops.document-inspector.v1"
PAGE_TYPES = {
    "DIGITAL_TEXT",
    "SCANNED_IMAGE",
    "MIXED_CONTENT",
    "LOW_QUALITY",
    "EMPTY_OR_UNREADABLE",
}


def _safe_words(page: Any) -> list[tuple[Any, ...]]:
    try:
        return list(page.get_text("words") or [])
    except Exception:
        return []


def _safe_text(page: Any) -> str:
    try:
        return str(page.get_text("text") or "")
    except Exception:
        return ""


def _table_signal(page: Any, words: list[tuple[Any, ...]]) -> dict[str, Any]:
    """Use PyMuPDF's table detector when available, otherwise use line signals."""
    tables = []
    detector = getattr(page, "find_tables", None)
    if callable(detector):
        try:
            found = detector()
            tables = list(getattr(found, "tables", found or []))
        except Exception:
            tables = []
    horizontal = vertical = 0
    try:
        for drawing in page.get_drawings() or []:
            rect = drawing.get("rect")
            if not rect:
                continue
            if rect.width >= 100 and rect.height <= 2:
                horizontal += 1
            if rect.height >= 30 and rect.width <= 2:
                vertical += 1
    except Exception:
        pass
    repeated_x = len(Counter(round(float(w[0]), 1) for w in words if len(w) > 0).most_common(3)) >= 2
    estimated = bool(tables) or (horizontal >= 2 and vertical >= 2) or (repeated_x and horizontal >= 1)
    return {
        "present": estimated,
        "count": len(tables),
        "detector": "pymupdf.find_tables" if tables else ("graphics_heuristic" if estimated else "none"),
        "horizontal_rules": horizontal,
        "vertical_rules": vertical,
    }


def _quality(text: str, words: list[tuple[Any, ...]], page_area: float) -> tuple[float, dict[str, Any]]:
    compact = re.sub(r"\s+", " ", text).strip()
    replacement_count = text.count("\ufffd") + len(re.findall(r"\(cid:\d+\)", text, re.I))
    repeated_lines = sum(count - 1 for count in Counter(
        line.strip() for line in text.splitlines() if line.strip()
    ).values() if count > 1)
    abnormal_spaces = len(re.findall(r"\S {5,}\S", text))
    density = len(compact) / max(page_area, 1.0)
    penalties = 0.0
    if not compact:
        penalties += 0.70
    if len(words) < 8 and compact:
        penalties += 0.18
    if replacement_count:
        penalties += min(0.45, replacement_count * 0.08)
    if abnormal_spaces:
        penalties += min(0.20, abnormal_spaces * 0.04)
    if repeated_lines:
        penalties += min(0.15, repeated_lines * 0.03)
    score = max(0.0, min(1.0, 1.0 - penalties))
    return round(score, 4), {
        "text_density": round(density, 6),
        "replacement_characters": replacement_count,
        "repeated_lines": repeated_lines,
        "abnormal_spacing_sequences": abnormal_spaces,
        "text_is_empty": not bool(compact),
    }


def inspect_page(page: Any, page_number: int) -> dict[str, Any]:
    rect = getattr(page, "rect", None)
    width = float(getattr(rect, "width", 0.0) or 0.0)
    height = float(getattr(rect, "height", 0.0) or 0.0)
    area = max(width * height, 1.0)
    words = _safe_words(page)
    text = _safe_text(page)
    images = []
    try:
        images = list(page.get_image_info(xrefs=True) or [])
    except Exception:
        try:
            images = [{"xref": item[0]} for item in (page.get_images(full=True) or [])]
        except Exception:
            images = []
    try:
        graphics = len(page.get_drawings() or [])
    except Exception:
        graphics = 0
    quality, quality_signals = _quality(text, words, area)
    has_text = bool(text.strip()) and bool(words)
    has_images = bool(images)
    if not has_text and not has_images:
        page_type = "EMPTY_OR_UNREADABLE"
    elif has_text and quality < 0.55:
        page_type = "LOW_QUALITY"
    elif has_images and has_text:
        page_type = "MIXED_CONTENT"
    elif has_images:
        page_type = "SCANNED_IMAGE"
    elif has_text:
        page_type = "DIGITAL_TEXT"
    else:
        page_type = "EMPTY_OR_UNREADABLE"
    resolutions = [
        (float(info.get("xres")), float(info.get("yres")))
        for info in images
        if info.get("xres") and info.get("yres")
    ]
    visual_regions = []
    for index, info in enumerate(images, 1):
        bbox = info.get("bbox") if isinstance(info, dict) else None
        if not bbox or len(bbox) < 4:
            continue
        visual_regions.append({
            "region_id": f"P{page_number:03d}-IMG{index:03d}",
            "bbox": [round(float(value), 2) for value in bbox[:4]],
            "width": int(info.get("width", 0) or 0),
            "height": int(info.get("height", 0) or 0),
            "xres": round(float(info.get("xres", 0) or 0), 2),
            "yres": round(float(info.get("yres", 0) or 0), 2),
        })
    issues = []
    if page_type == "EMPTY_OR_UNREADABLE":
        issues.append({"code": "EMPTY_OR_UNREADABLE", "severity": "high", "message": "No se obtuvo texto ni imagen utilizable."})
    if page_type == "LOW_QUALITY":
        issues.append({"code": "LOW_EXTRACTION_QUALITY", "severity": "high", "message": "La extracción contiene señales de posible omisión o corrupción."})
    if quality_signals["replacement_characters"]:
        issues.append({"code": "CORRUPT_CHARACTERS", "severity": "high", "message": "Se detectaron caracteres de sustitución o CID."})
    if page_type == "MIXED_CONTENT" and not visual_regions:
        issues.append({"code": "MIXED_REGIONS_UNLOCATED", "severity": "medium", "message": "La página contiene imágenes, pero no fue posible localizar sus regiones."})
    return {
        "page": int(page_number),
        "width": round(width, 2),
        "height": round(height, 2),
        "orientation": "landscape" if width > height else ("portrait" if height > width else "square"),
        "page_type": page_type,
        "text_length": len(text),
        "word_count": len(words),
        "native_text": text,
        "has_native_text": has_text,
        "image_count": len(images),
        "has_images": has_images,
        "graphic_element_count": graphics,
        "image_resolutions": [[round(x, 2), round(y, 2)] for x, y in resolutions],
        "visual_regions": visual_regions,
        "resolution_available": bool(resolutions),
        "tables": _table_signal(page, words),
        "quality_score": quality,
        "quality_signals": quality_signals,
        "scan_indicators": {
            "image_backed": has_images,
            "text_sparse": len(words) < 18,
            "corrupt_characters": bool(quality_signals["replacement_characters"]),
        },
        "processing_status": "INSPECTED",
        "issues": issues,
    }


def inspect_pdf(pdf_path: str | Path) -> dict[str, Any]:
    """Inspect 100% of pages and return a serializable report."""
    path = Path(pdf_path)
    try:
        document = fitz.open(str(path))
    except Exception as exc:
        raise ValueError(f"No se pudo inspeccionar el PDF: {exc}") from exc
    pages: list[dict[str, Any]] = []
    expected_pages = 0
    try:
        expected_pages = len(document)
        for number, page in enumerate(document, 1):
            pages.append(inspect_page(page, number))
    finally:
        document.close()
    counts = {kind: sum(item["page_type"] == kind for item in pages) for kind in PAGE_TYPES}
    return {
        "schema_version": INSPECTOR_VERSION,
        "total_pages": len(pages),
        "inspected_pages": len(pages),
        "coverage": round(len(pages) / max(1, expected_pages), 4),
        "classification_counts": counts,
        "pages": pages,
        "all_pages_inspected": len(pages) == expected_pages,
    }
