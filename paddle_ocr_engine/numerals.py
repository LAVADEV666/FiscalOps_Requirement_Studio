from __future__ import annotations

import re
from typing import Any

# La sustitución OCR se limita al prefijo candidato; jamás al texto jurídico.
_PREFIX = re.compile(
    r"^\s*([0-9IlOo]{1,3}(?:\s*[.]\s*[0-9IlOo]{1,3}){0,3})\s*(?:[.)\-–—:]|\s)\s*(.*)$",
    re.S,
)


def normalize_numeral(value: str) -> str:
    parts = re.split(r"\s*[.]\s*", value.strip())
    translated = [p.translate(str.maketrans({"I": "1", "l": "1", "O": "0", "o": "0"})) for p in parts]
    if not translated or any(not p.isdigit() for p in translated):
        return ""
    normalized = ".".join(str(int(p)) for p in translated)
    return normalized if all(0 <= int(p) <= 999 for p in translated) else ""


def detect_numerals(blocks: list[dict[str, Any]], page_width: float | None = None) -> list[dict[str, Any]]:
    """Detecta numerales usando texto, geometría y confianza del bloque."""
    if not blocks:
        return []
    width = float(page_width or max((b.get("bbox", [0, 0, 0, 0])[2] for b in blocks), default=1) or 1)
    found: list[dict[str, Any]] = []
    for block in sorted(blocks, key=lambda b: (b.get("bbox", [0, 0, 0, 0])[1], b.get("bbox", [0, 0, 0, 0])[0])):
        text = str(block.get("text", "")).strip()
        match = _PREFIX.match(text)
        if not match:
            continue
        numeral = normalize_numeral(match.group(1))
        if not numeral:
            continue
        bbox = block.get("bbox", [0, 0, 0, 0])
        left_ratio = float(bbox[0] or 0) / width
        geometry_score = 1.0 if left_ratio <= 0.30 else (0.75 if left_ratio <= 0.48 else 0.45)
        ocr_score = float(block.get("confidence", 0) or 0)
        score = round(ocr_score * 0.75 + geometry_score * 0.25, 4)
        found.append({
            "numeral": numeral,
            "level": numeral.count("."),
            "text": match.group(2).strip(),
            "bbox": bbox,
            "block_id": block.get("block_id", ""),
            "confidence": score,
            "requires_review": score < 0.90,
        })
    return found


def sequence_warnings(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    mains = [int(x["numeral"]) for x in items if str(x.get("numeral", "")).isdigit()]
    warnings: list[dict[str, str]] = []
    if len(mains) != len(set(mains)):
        warnings.append({"code": "DUPLICATE_NUMERAL", "message": "Hay numerales principales duplicados."})
    if mains:
        expected = list(range(min(mains), max(mains) + 1))
        if mains != expected:
            warnings.append({"code": "BROKEN_NUMERAL_SEQUENCE", "message": f"Secuencia {mains}; esperada {expected}."})
    return warnings
