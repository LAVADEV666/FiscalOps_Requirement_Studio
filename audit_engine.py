from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
import pdfplumber

POINT_LINE = re.compile(r"^\s*(\d{1,2})\s*(?:\.\s*[-–—]?|[-–—]|\))\s*(?=\S)")
ABBREVIATIONS = {"R.F.C.", "S.A.", "S.C.", "C.V.", "C.P.", "L.A.", "A.C.", "M.N."}
EVIDENCE_RULES = {
    "escrito_libre": ("escrito libre",),
    "excel": ("formato excel", ".xlsx", "papel de trabajo"),
    "cfdi": ("cfdi", "comprobante fiscal"),
    "estado_cuenta": ("estado de cuenta", "estados de cuenta"),
    "contrato": ("contrato", "convenio", "acuerdo"),
    "contabilidad": ("registro contable", "balanza", "libro diario", "auxiliar contable"),
    "pedimento": ("pedimento",),
    "acta": ("acta de asamblea",),
    "materialidad": ("reporte fotográfico", "informe", "entregable", "materializó"),
    "comprobante_pago": ("transferencia", "cheque", "comprobante de pago"),
}


def _group_lines(words: list[dict[str, Any]], tolerance: float = 3.5) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for word in sorted(words, key=lambda w: (round(w["top"] / tolerance), w["x0"])):
        if not lines or abs(lines[-1]["top"] - word["top"]) > tolerance:
            lines.append({"words": [word], "top": word["top"]})
        else:
            lines[-1]["words"].append(word)
    result = []
    for line in lines:
        ws = sorted(line["words"], key=lambda w: w["x0"])
        result.append({
            "text": " ".join(w["text"] for w in ws),
            "x0": min(w["x0"] for w in ws), "x1": max(w["x1"] for w in ws),
            "top": min(w["top"] for w in ws), "bottom": max(w["bottom"] for w in ws),
        })
    return result


def build_fragments(pdf_path: Path, points: list[dict[str, Any]], ocr_pages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    ocr_by_page = {int(x.get("page", 0)): x for x in (ocr_pages or []) if x.get("page")}
    with pdfplumber.open(pdf_path) as pdf:
        page_lines = []
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
            page_lines.append(_group_lines(words))
        markers: dict[int, list[tuple[int, float]]] = {}
        for page_no, lines in enumerate(page_lines, 1):
            for line in lines:
                match = POINT_LINE.match(line["text"])
                if match:
                    number = int(match.group(1))
                    if 1 <= number <= 100:
                        markers.setdefault(number, []).append((page_no, line["top"]))

        for point in points:
            number = int(point["number"])
            start_page, end_page = point["page_start"], point["page_end"]
            start_candidates = markers.get(number, [])
            start_top = next((top for page, top in start_candidates if page == start_page), 90.0)
            next_point = next((p for p in points if int(p["number"]) == number + 1), None)
            for page_no in range(start_page, end_page + 1):
                page = pdf.pages[page_no - 1]
                ocr_page = ocr_by_page.get(page_no)
                if ocr_page and ocr_page.get("text_blocks"):
                    blocks = ocr_page["text_blocks"]
                    candidates = [x for x in ocr_page.get("numerals", []) if str(x.get("numeral", "")).split(".")[0] == str(number)]
                    start_y = min((x.get("bbox", [0, 0, 0, 0])[1] for x in candidates), default=0)
                    later = [x for x in ocr_page.get("numerals", []) if str(x.get("numeral", "")).isdigit() and int(x["numeral"]) == number + 1]
                    end_y = min((x.get("bbox", [0, 0, 0, 0])[1] for x in later), default=float(ocr_page.get("height", 0) or max((b["bbox"][3] for b in blocks), default=1)))
                    selected = [b for b in blocks if b.get("bbox", [0, 0, 0, 0])[3] >= start_y and b.get("bbox", [0, 0, 0, 0])[1] < end_y]
                    if not selected:
                        selected = blocks
                    x0 = min(b["bbox"][0] for b in selected)
                    y0 = min(b["bbox"][1] for b in selected)
                    x1 = max(b["bbox"][2] for b in selected)
                    y1 = max(b["bbox"][3] for b in selected)
                    confidence = round(sum(float(b.get("confidence", 0)) for b in selected) / max(1, len(selected)), 4)
                    fragment_id = f"FRG-P{page_no:03d}-REQ{number:03d}-{len(fragments)+1:04d}"
                    fragments.append({
                        "fragment_id": fragment_id, "requirement_id": f"REQ-{number:03d}",
                        "type": "requirement", "page": page_no,
                        "bbox": {"x0": round(x0,2), "y0": round(y0,2), "x1": round(x1,2), "y1": round(y1,2)},
                        "page_size": {"width": float(ocr_page.get("width", 1)), "height": float(ocr_page.get("height", 1))},
                        "method": "paddleocr", "motor": ocr_page.get("engine_version", "paddleocr"),
                        "confidence": confidence, "requires_review": confidence < .90,
                        "source_text": point["text"], "status": "review" if confidence < .90 else "detected",
                    })
                    continue
                top = start_top if page_no == start_page else 75.0
                bottom = page.height - 68.0
                if next_point and page_no == next_point["page_start"]:
                    next_markers = markers.get(number + 1, [])
                    next_top = next((t for p, t in next_markers if p == page_no), None)
                    if next_top is not None:
                        bottom = max(top + 18, next_top - 6)
                lines = [line for line in page_lines[page_no - 1] if line["bottom"] >= top and line["top"] <= bottom]
                if lines:
                    x0 = max(0, min(line["x0"] for line in lines) - 5)
                    x1 = min(page.width, max(line["x1"] for line in lines) + 5)
                    y0 = max(0, min(line["top"] for line in lines) - 4)
                    y1 = min(page.height, max(line["bottom"] for line in lines) + 4)
                else:
                    x0, x1, y0, y1 = 40, page.width - 40, top, bottom
                fragment_id = f"FRG-P{page_no:03d}-REQ{number:03d}-{len(fragments)+1:04d}"
                fragments.append({
                    "fragment_id": fragment_id, "requirement_id": f"REQ-{number:03d}",
                    "type": "requirement", "page": page_no,
                    "bbox": {"x0": round(x0,2), "y0": round(y0,2), "x1": round(x1,2), "y1": round(y1,2)},
                    "page_size": {"width": round(page.width,2), "height": round(page.height,2)},
                    "method": "native", "confidence": 0.98,
                    "source_text": point["text"], "status": "detected"
                })
    return fragments


def requested_evidence(text: str) -> list[dict[str, str]]:
    folded = text.lower()
    return [{"type": kind, "status": "detected"} for kind, terms in EVIDENCE_RULES.items() if any(term in folded for term in terms)]


def validate_integrity(data: dict[str, Any]) -> dict[str, Any]:
    points = data.get("points", [])
    numbers = [int(p["number"]) for p in points]
    expected = list(range(1, max(numbers, default=0) + 1))
    alerts: list[dict[str, str]] = []
    if not points:
        alerts.append({"severity": "critical", "code": "NO_REQUIREMENTS", "message": "No se detectaron requerimientos."})
    if numbers != expected:
        alerts.append({"severity": "critical", "code": "BROKEN_SEQUENCE", "message": f"Secuencia detectada {numbers}; esperada {expected}."})
    if len(numbers) != len(set(numbers)):
        alerts.append({"severity": "critical", "code": "DUPLICATE_NUMBER", "message": "Existen numerales duplicados."})
    for point in points:
        if len(point.get("text", "").strip()) < 20:
            alerts.append({"severity": "high", "code": "SHORT_REQUIREMENT", "message": f"Numeral {point['number']} con texto insuficiente."})
        if not point.get("fragment_ids"):
            alerts.append({"severity": "high", "code": "NO_TRACE", "message": f"Numeral {point['number']} sin fragmentos vinculados."})
        point["requested_evidence"] = requested_evidence(point.get("text", ""))
    metadata = data.get("metadata_validation", {}).get("fields", {})
    critical_fields = ("rfc", "office", "reference", "date", "deadline")
    metadata_ok = sum(1 for key in critical_fields if metadata.get(key, {}).get("valid"))
    trace_ok = sum(1 for p in points if p.get("fragment_ids"))
    structural = 100 if numbers == expected and numbers else 0
    trace = round(100 * trace_ok / max(1, len(points)))
    fields_score = round(100 * metadata_ok / len(critical_fields))
    evidence_score = round(100 * sum(bool(p.get("requested_evidence")) for p in points) / max(1, len(points)))
    completeness = round(structural * .45 + trace * .25 + fields_score * .20 + evidence_score * .10)
    return {"completeness": completeness, "alerts": alerts, "metrics": {"structure": structural, "traceability": trace, "critical_fields": fields_score, "evidence": evidence_score}}


def render_pages(pdf_path: Path, target: Path, scale: float = 1.45) -> list[dict[str, Any]]:
    target.mkdir(parents=True, exist_ok=True)
    result = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            name = f"page-{index}.png"
            pix.save(target / name)
            result.append({"page": index, "file": name, "width": pix.width, "height": pix.height})
    return result


def audit_event(action: str, requirement_id: str = "", fragment_id: str = "", before: str = "", after: str = "") -> dict[str, str]:
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "action": action, "requirement_id": requirement_id, "fragment_id": fragment_id, "before": before, "after": after, "actor": "local_user"}

# Optional multimodal layer. Existing deterministic audit functions remain the default.
try:
    from ai_engine import FiscalOpsAIEngine
except Exception:
    FiscalOpsAIEngine = None

def ai_status(base_dir: Path | None = None) -> dict[str, Any]:
    if FiscalOpsAIEngine is None:
        return {'available': False, 'mode': 'deterministic_fallback', 'reason': 'AI module unavailable'}
    return FiscalOpsAIEngine((base_dir or Path(__file__).resolve().parent)/'models'/'donut-docvqa').status()
