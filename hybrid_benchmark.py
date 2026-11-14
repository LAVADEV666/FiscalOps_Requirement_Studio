"""Reproducible benchmark for native, PaddleOCR and hybrid routing.

The manifest must contain verified ground truth.  Missing OCR/model stages are
reported as NOT_RUN; they are never converted into passing metrics.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

import fitz

from cross_validation import cer, wer
from document_inspector import inspect_pdf
from ocr_decision_engine import decide_document
from ocr_engine import OCREngine
from ollama_provider import OllamaClient


def _validate(rows: list[dict[str, Any]]) -> list[str]:
    errors = []
    for index, row in enumerate(rows, 1):
        if row.get("ground_truth_status") != "verified":
            errors.append(f"Fila {index}: ground_truth_status debe ser verified.")
        if not str(row.get("pdf", "")).strip() or int(row.get("page", 0) or 0) < 1:
            errors.append(f"Fila {index}: pdf/page inválido.")
        if not isinstance(row.get("text"), str):
            errors.append(f"Fila {index}: text debe ser texto validado.")
    return errors


def run_benchmark(manifest: str | Path, output: str | Path, *, pilot: bool = False) -> dict[str, Any]:
    manifest_path = Path(manifest)
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = _validate(rows)
    if errors:
        raise ValueError("Manifest inválido: " + " ".join(errors))
    base = manifest_path.parent
    stages = {"native": {"status": "RUN", "cases": 0}, "paddleocr": {"status": "NOT_RUN", "cases": 0}, "hybrid": {"status": "RUN", "cases": 0}, "ollama": {"status": "NOT_RUN", "cases": 0}}
    details = []
    total = {"cer": [], "wer": [], "seconds": [], "pages_inspected": 0, "pages_total": 0}
    tracemalloc.start()
    started_total = time.perf_counter()
    with tempfile.TemporaryDirectory() as temporary_path:
        temporary = Path(temporary_path)
        engine = None
        ocr_available = None
        for case_number, row in enumerate(rows, 1):
            pdf_path = (base / row["pdf"]).resolve()
            page_number = int(row["page"])
            inspection_started = time.perf_counter()
            inspection = inspect_pdf(pdf_path)
            decisions = decide_document(inspection)
            with fitz.open(str(pdf_path)) as document:
                if page_number > len(document):
                    raise ValueError(f"Fila {case_number}: página fuera de rango.")
                page = document[page_number - 1]
                native_text = str(page.get_text("text") or "")
                page_kind = inspection["pages"][page_number - 1]["page_type"]
                decision = decisions["pages"][page_number - 1]
                ocr_text = None
                ocr_error = None
                if decision.get("ocr_required") and ocr_available is None:
                    engine = OCREngine(temporary / "ocr-cache")
                    try:
                        ocr_available = bool(engine.is_usable())
                    except Exception:
                        ocr_available = False
                    if ocr_available:
                        stages["paddleocr"]["status"] = "RUN"
                if decision.get("ocr_required") and ocr_available and engine is not None:
                    image = temporary / f"case-{case_number}.png"
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72), alpha=False)
                    pixmap.save(str(image))
                    try:
                        ocr_text = str(engine.run(image, force=True).get("text", ""))
                    except Exception as exc:
                        ocr_error = type(exc).__name__
                elapsed = time.perf_counter() - inspection_started
            expected = str(row["text"])
            measured = decision["action"] == "NATIVE_ONLY" or ocr_text is not None
            actual = native_text if decision["action"] == "NATIVE_ONLY" else (ocr_text or "")
            if decision["action"] == "NATIVE_ONLY":
                stages["native"]["cases"] += 1
            if ocr_text is not None:
                stages["paddleocr"]["cases"] += 1
            stages["hybrid"]["cases"] += 1
            if measured:
                total["cer"].append(cer(expected, actual)); total["wer"].append(wer(expected, actual))
            total["seconds"].append(elapsed)
            total["pages_inspected"] += inspection["inspected_pages"]; total["pages_total"] += inspection["total_pages"]
            details.append({"case": case_number, "pdf": str(row["pdf"]), "page": page_number, "page_type": page_kind, "route": decision["action"], "measured": measured, "cer": cer(expected, actual) if measured else None, "wer": wer(expected, actual) if measured else None, "ocr_status": "RUN" if ocr_text is not None else ("NOT_RUN" if ocr_available is False or decision.get("ocr_required") else "N/A"), "ocr_error": ocr_error, "inspection_coverage": inspection["coverage"], "seconds": round(elapsed, 4)})
    _, peak_memory = tracemalloc.get_traced_memory(); tracemalloc.stop()
    ollama_status = OllamaClient().status()
    stages["ollama"] = {"status": "AVAILABLE" if ollama_status.get("model_available") else "NOT_RUN", "model": ollama_status.get("model"), "reason": ollama_status.get("reason", "Modelo no disponible o desactivado.")}
    report = {
        "schema_version": "fiscalops.hybrid-benchmark.v1",
        "manifest": {"path": str(manifest_path), "cases": len(rows), "ground_truth": "verified", "pilot": pilot},
        "stages": stages,
        "metrics": {"cer": round(sum(total["cer"]) / max(1, len(total["cer"])), 6) if total["cer"] else None, "wer": round(sum(total["wer"]) / max(1, len(total["wer"])), 6) if total["wer"] else None, "measured_cases": len(total["cer"]), "page_coverage": round(total["pages_inspected"] / max(1, total["pages_total"]), 6), "seconds_per_case": round(sum(total["seconds"]) / max(1, len(total["seconds"])), 4), "peak_memory_bytes": peak_memory},
        "details": details,
        "promotable": bool(rows) and all(item["measured"] and item["ocr_status"] != "ERROR" for item in details),
        "fidelity_claim": "MEASURED_AGAINST_VERIFIED_REFERENCE",
    }
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark híbrido local de FiscalOps")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("hybrid_benchmark_report.json"))
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    report = run_benchmark(args.manifest, args.output, pilot=args.pilot)
    print(json.dumps({"metrics": report["metrics"], "stages": report["stages"], "promotable": report["promotable"]}, ensure_ascii=False, indent=2))
    return 0 if report["promotable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
