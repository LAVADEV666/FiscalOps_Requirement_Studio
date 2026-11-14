"""Cross-source validation and document-quality metrics."""
from __future__ import annotations

import re
from typing import Any


VALIDATION_VERSION = "fiscalops.cross-validation.v1"
CRITICAL_PATTERNS = {
    "rfc": re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b", re.I),
    "curp": re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b", re.I),
    "amount": re.compile(r"\$?\d[\d,]*(?:\.\d{2})?"),
    "date_or_period": re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:19|20)\d{2}\b"),
    "percentage": re.compile(r"\b\d+(?:\.\d+)?\s*%"),
    "folio": re.compile(r"\b[A-Z0-9]{2,}(?:[-/][A-Z0-9]{2,}){1,}\b", re.I),
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def cer(reference: str, hypothesis: str) -> float:
    a, b = _compact(reference), _compact(hypothesis)
    if not a:
        return 0.0 if not b else 1.0
    previous = list(range(len(b) + 1))
    for index, character in enumerate(a, 1):
        current = [index]
        for other_index, other in enumerate(b, 1):
            current.append(min(
                current[-1] + 1,
                previous[other_index] + 1,
                previous[other_index - 1] + (character != other),
            ))
        previous = current
    return round(previous[-1] / len(a), 6)


def wer(reference: str, hypothesis: str) -> float:
    a, b = _compact(reference).split(), _compact(hypothesis).split()
    if not a:
        return 0.0 if not b else 1.0
    previous = list(range(len(b) + 1))
    for i, word in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (word != other)))
        previous = current
    return round(previous[-1] / len(a), 6)


def _tokens(text: str) -> dict[str, list[str]]:
    return {name: sorted(set(match.group(0).upper() for match in pattern.finditer(text or ""))) for name, pattern in CRITICAL_PATTERNS.items()}


def validate_cross_sources(reconstruction: dict[str, Any], data: dict[str, Any], reference_text: str | None = None) -> dict[str, Any]:
    text = str(reconstruction.get("text", ""))
    critical = _tokens(text)
    discrepancies: list[dict[str, Any]] = []
    for page in reconstruction.get("pages", []):
        all_blocks = [*page.get("blocks", []), *page.get("supplemental_blocks", [])]
        for block in all_blocks:
            if block.get("validation_status") == "REVIEW_REQUIRED":
                discrepancies.append({
                    "page": page.get("page"),
                    "block_id": block.get("fragment_id"),
                    "kind": "LOW_CONFIDENCE_OCR",
                    "message": "El bloque OCR requiere revisión humana.",
                    "sources": [block.get("source")],
                })
        native_text = str(page.get("native_text", "") or "")
        selected_text = str(page.get("text", "") or "")
        ocr_text = "\n".join(
            str(block.get("text", "")) for block in all_blocks
            if block.get("source") in {"PADDLE_OCR", "OCR_RETRY", "MANUAL_CORRECTION"}
        ).strip()
        if native_text and ocr_text:
            native_tokens = _tokens(native_text)
            ocr_tokens = _tokens(ocr_text)
            page["source_comparisons"] = [{
                "kind": "NATIVE_VS_OCR",
                "native_cer_against_ocr": cer(native_text, ocr_text),
                "native_wer_against_ocr": wer(native_text, ocr_text),
                "native_critical_tokens": native_tokens,
                "ocr_critical_tokens": ocr_tokens,
                "critical_token_differences": {
                    name: {
                        "native_only": sorted(set(native_tokens[name]) - set(ocr_tokens[name])),
                        "ocr_only": sorted(set(ocr_tokens[name]) - set(native_tokens[name])),
                    } for name in native_tokens
                },
            }]
        region_comparisons = []
        for block in page.get("supplemental_blocks", []):
            region_tokens = _tokens(block.get("text", ""))
            baseline_tokens = _tokens(native_text or selected_text)
            overlap = {kind: sorted(set(region_tokens[kind]) & set(baseline_tokens[kind])) for kind in region_tokens}
            supplemental = {kind: sorted(set(region_tokens[kind]) - set(baseline_tokens[kind])) for kind in region_tokens}
            region_comparisons.append({"block_id": block.get("fragment_id"), "overlap": overlap, "supplemental_critical_tokens": supplemental})
        if region_comparisons:
            page.setdefault("source_comparisons", []).extend(region_comparisons)
    fields = data.get("metadata_validation", {}).get("fields", {})
    all_source_text = "\n".join(
        [text] + [
            "\n".join([
                str(page.get("native_text", "") or ""),
                str(page.get("text", "") or ""),
                *[str(block.get("text", "") or "") for block in [*page.get("blocks", []), *page.get("supplemental_blocks", [])]],
            ]) for page in reconstruction.get("pages", [])
        ]
    )
    critical_fields = {}
    for name, field in fields.items():
        if name not in {"rfc", "office", "reference", "date", "deadline", "period", "amount", "curp"}:
            continue
        value = str(field.get("value", ""))
        placeholder = not value or value.startswith("[")
        source_page = field.get("page")
        source_engine = ""
        if not source_page and not placeholder:
            for page in reconstruction.get("pages", []):
                candidates = (("PDF_NATIVE", page.get("native_text", "")), ("RECONSTRUCTED", page.get("text", "")))
                for candidate_source, candidate_text in candidates:
                    if value.upper() in str(candidate_text).upper():
                        source_page = page.get("page")
                        source_engine = candidate_source
                        break
                if source_page:
                    break
        if not source_engine and source_page:
            source_engine = str(field.get("source_engine", "deterministic_extraction"))
        critical_fields[name] = {
            "value": value if not placeholder else "",
            "source": field.get("source", "deterministic_extraction"),
            "source_engine": source_engine,
            "page": source_page,
            "validated": not placeholder and value.upper() in all_source_text.upper(),
            "requires_review": placeholder or value.upper() not in all_source_text.upper() or source_page is None,
        }
    metrics = {
        "page_coverage": round(reconstruction.get("non_empty_pages", 0) / max(1, reconstruction.get("page_count", 0)) * 100, 2),
        "critical_fields_traced": round(sum(bool(item.get("source")) and bool(item.get("page")) for item in critical_fields.values()) / max(1, len(critical_fields)) * 100, 2),
        "critical_fields_validated": round(sum(bool(item.get("validated")) for item in critical_fields.values()) / max(1, len(critical_fields)) * 100, 2),
        "discrepancy_count": len(discrepancies),
        "mixed_regions_processed": sum(len(page.get("supplemental_blocks", [])) for page in reconstruction.get("pages", [])),
    }
    if reference_text is not None:
        metrics.update({"cer": cer(reference_text, text), "wer": wer(reference_text, text), "reference_available": True})
    else:
        metrics["reference_available"] = False
    return {
        "schema_version": VALIDATION_VERSION,
        "critical_tokens": critical,
        "critical_fields": critical_fields,
        "discrepancies": discrepancies,
        "metrics": metrics,
        "requires_human_review": bool(discrepancies) or any(item.get("requires_review") for item in critical_fields.values()),
        "fidelity_claim": "NOT_DECLARED_WITHOUT_REFERENCE" if reference_text is None else "MEASURED_AGAINST_REFERENCE",
    }
