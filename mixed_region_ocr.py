"""OCR only the image regions discovered on mixed-content PDF pages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz

from ocr_engine import OCREngine
from config import OCR_RENDER_DPI, ocr_dpi_for_page


MIXED_OCR_VERSION = "fiscalops.mixed-region-ocr.v1"


def run_mixed_region_ocr(
    pdf_path: str | Path,
    target_dir: str | Path,
    inspection: dict[str, Any],
    ocr_service: OCREngine,
    *,
    enabled: bool = True,
    dpi: int = OCR_RENDER_DPI,
    min_area_ratio: float = 0.02,
    max_regions_per_page: int = 8,
) -> dict[str, Any]:
    """Return supplemental OCR results without duplicating native page text."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schema_version": MIXED_OCR_VERSION,
        "regions": [],
        "summary": {"pages": 0, "regions": 0, "processed": 0, "review_required": 0, "skipped": 0},
    }
    mixed_pages = [page for page in inspection.get("pages", []) if page.get("page_type") == "MIXED_CONTENT"]
    result["summary"]["pages"] = len(mixed_pages)
    if not mixed_pages:
        return result
    if not enabled:
        result["status"] = "NOT_REQUESTED"
        result["summary"]["skipped"] = len(mixed_pages)
        return result
    try:
        usable = bool(ocr_service.is_usable())
    except Exception as exc:
        usable = False
        result["error"] = f"No se pudo comprobar PaddleOCR: {exc}"
    if not usable:
        result["status"] = "PADDLEOCR_UNAVAILABLE"
        result["summary"]["skipped"] = len(mixed_pages)
        return result
    with fitz.open(str(pdf_path)) as document:
        for page_info in mixed_pages:
            page_number = int(page_info.get("page", 0))
            if not 1 <= page_number <= len(document):
                continue
            page = document[page_number - 1]
            page_area = max(float(page.rect.width * page.rect.height), 1.0)
            regions = page_info.get("visual_regions", [])[:max_regions_per_page]
            for region in regions:
                bbox = region.get("bbox", [])
                if len(bbox) < 4:
                    continue
                rect = fitz.Rect(*map(float, bbox)) & page.rect
                if rect.is_empty or rect.get_area() / page_area < min_area_ratio:
                    continue
                region_id = str(region.get("region_id") or f"P{page_number:03d}-IMG{len(result['regions']) + 1:03d}")
                image_path = target / f"page-{page_number:03d}-{region_id}.png"
                try:
                    region_dpi = min(float(dpi), ocr_dpi_for_page(page.rect.width, page.rect.height))
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(region_dpi / 72, region_dpi / 72), clip=rect, alpha=False)
                    pixmap.save(str(image_path))
                    ocr_result = ocr_service.run(image_path, force=True)
                    item = {
                        **ocr_result,
                        "page": page_number,
                        "region_id": region_id,
                        "region_bbox": [round(float(value), 2) for value in rect],
                        "source": "PADDLE_OCR",
                        "processing_status": "PROCESSED",
                    }
                except Exception as exc:
                    item = {
                        "page": page_number,
                        "region_id": region_id,
                        "region_bbox": [round(float(value), 2) for value in rect],
                        "source": "OCR_RETRY",
                        "processing_status": "FAILED",
                        "text": "",
                        "text_blocks": [],
                        "requires_review": True,
                        "error": str(exc),
                    }
                result["regions"].append(item)
                result["summary"]["regions"] += 1
                result["summary"]["processed"] += int(item.get("processing_status") == "PROCESSED")
                result["summary"]["review_required"] += int(bool(item.get("requires_review")))
    result["status"] = "PROCESSED" if result["summary"]["processed"] else "NO_REGIONS_PROCESSED"
    (target / "mixed-region-summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
