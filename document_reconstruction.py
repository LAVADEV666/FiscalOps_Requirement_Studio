"""Canonical reconstruction with page and extraction-source traceability."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz


RECONSTRUCTION_VERSION = "fiscalops.reconstruction.v1"


def _native_blocks(page: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, item in enumerate(page.get_text("blocks") or [], 1):
        text = str(item[4] if len(item) > 4 else "").strip()
        if not text:
            continue
        blocks.append({
            "fragment_id": f"PDF-P{getattr(page, 'number', 0) + 1:03d}-B{index:03d}",
            "text": text,
            "page": getattr(page, "number", 0) + 1,
            "bbox": [round(float(item[0]), 2), round(float(item[1]), 2), round(float(item[2]), 2), round(float(item[3]), 2)],
            "source": "PDF_NATIVE",
            "confidence": None,
            "confidence_kind": "native_extraction",
            "validation_status": "UNVALIDATED",
        })
    return blocks


def reconstruct_document(pdf_path: str | Path, inspection: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    ocr_pages = {int(item.get("page", 0)): item for item in data.get("ocr_diagnostics", {}).get("pages", [])}
    mixed_regions = {}
    for item in data.get("ocr_diagnostics", {}).get("mixed_regions", []):
        mixed_regions.setdefault(int(item.get("page", 0)), []).append(item)
    pages: list[dict[str, Any]] = []
    with fitz.open(str(pdf_path)) as document:
        for index, page in enumerate(document, 1):
            ocr_page = ocr_pages.get(index)
            if ocr_page and ocr_page.get("text_blocks"):
                blocks = [{
                    "fragment_id": item.get("block_id") or f"OCR-P{index:03d}-B{position:03d}",
                    "text": str(item.get("text", "")),
                    "page": index,
                    "bbox": item.get("bbox", []),
                    "source": "PADDLE_OCR",
                    "confidence": item.get("confidence", 0.0),
                    "confidence_kind": "ocr_original",
                    "validation_status": "REVIEW_REQUIRED" if item.get("requires_review") else "UNVALIDATED",
                } for position, item in enumerate(ocr_page.get("text_blocks", []), 1) if str(item.get("text", "")).strip()]
                text = str(ocr_page.get("text", ""))
            else:
                blocks = _native_blocks(page)
                text = str(page.get_text("text") or "")
            supplemental = []
            for region in mixed_regions.get(index, []):
                for position, item in enumerate(region.get("text_blocks", []), 1):
                    if not str(item.get("text", "")).strip():
                        continue
                    supplemental.append({
                        "fragment_id": item.get("block_id") or f"{region.get('region_id', 'REGION')}-B{position:03d}",
                        "text": str(item.get("text", "")),
                        "page": index,
                        "bbox": item.get("bbox", []),
                        "region_bbox": region.get("region_bbox", []),
                        "source": region.get("source", "PADDLE_OCR"),
                        "confidence": item.get("confidence", 0.0),
                        "confidence_kind": "ocr_original",
                        "validation_status": "REVIEW_REQUIRED" if item.get("requires_review") else "UNMATCHED_REGION",
                    })
            pages.append({
                "page": index,
                "page_type": next((x.get("page_type") for x in inspection.get("pages", []) if int(x.get("page", 0)) == index), "EMPTY_OR_UNREADABLE"),
                "text": text,
                "blocks": blocks,
                "supplemental_blocks": supplemental,
                "source_priority": list(dict.fromkeys([*(block.get("source") for block in blocks), *(block.get("source") for block in supplemental)])),
                "status": "RECONSTRUCTED" if text.strip() else "EMPTY_OR_UNREADABLE",
            })
    canonical = "\n\n".join(f"[PÁGINA {item['page']}]\n{item['text'].strip()}" for item in pages)
    return {
        "schema_version": RECONSTRUCTION_VERSION,
        "pages": pages,
        "text": canonical,
        "page_count": len(pages),
        "non_empty_pages": sum(bool(item["text"].strip()) for item in pages),
        "source_counts": {
            source: sum(1 for page in pages for block in [*page["blocks"], *page.get("supplemental_blocks", [])] if block.get("source") == source)
            for source in ("PDF_NATIVE", "PADDLE_OCR", "OCR_RETRY", "MANUAL_CORRECTION")
        },
        "no_silent_corrections": True,
    }
