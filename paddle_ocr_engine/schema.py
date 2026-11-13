from __future__ import annotations

from typing import Any, Iterable

SCHEMA_VERSION = "1.0.0"
ENGINE_VERSION = "fiscalops.paddleocr.v2"


def confidence01(value: Any) -> float:
    """Normaliza cualquier confianza OCR al contrato público 0..1."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1:
        score /= 100.0
    return round(max(0.0, min(1.0, score)), 4)


def polygon_bbox(points: Iterable[Any]) -> list[float]:
    """Convierte cuadriláteros Paddle o bbox planos a [x0,y0,x1,y1]."""
    raw = list(points or [])
    if len(raw) == 4 and all(isinstance(v, (int, float)) for v in raw):
        x0, y0, x1, y1 = map(float, raw)
        return [round(min(x0, x1), 2), round(min(y0, y1), 2),
                round(max(x0, x1), 2), round(max(y0, y1), 2)]
    pairs: list[tuple[float, float]] = []
    for point in raw:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                pairs.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not pairs:
        return [0.0, 0.0, 0.0, 0.0]
    xs, ys = zip(*pairs)
    return [round(min(xs), 2), round(min(ys), 2),
            round(max(xs), 2), round(max(ys), 2)]


def make_block(text: str, confidence: Any, bbox: Iterable[Any], *,
               block_type: str = "text", block_id: str = "") -> dict[str, Any]:
    return {
        "block_id": block_id,
        "type": block_type,
        "text": str(text or "").strip(),
        "confidence": confidence01(confidence),
        "bbox": polygon_bbox(bbox),
        "motor": ENGINE_VERSION,
        "requires_review": confidence01(confidence) < 0.90,
    }


def empty_result(page_file: str, error: str = "") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "page_file": page_file,
        "text": "",
        "confidence": 0.0,
        "text_blocks": [],
        "tables": [],
        "regions": [],
        "numerals": [],
        "quality": {},
        "preprocessing_profile": "none",
        "requires_review": True,
        "error": error,
    }
