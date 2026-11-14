from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pymupdf

from ocr_engine import OCREngine
from config import ocr_dpi_for_page

CATEGORIES = ("digital", "scanned_good", "scanned_regular", "scanned_bad")
REQUIRED_COUNTS = {name: 10 for name in CATEGORIES}


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for index, char_left in enumerate(left, 1):
        current = [index]
        for other_index, char_right in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[other_index] + 1, previous[other_index - 1] + (char_left != char_right)))
        previous = current
    return previous[-1]


def native_numerals(text: str) -> list[str]:
    expression = re.compile(r"(?m)^\s*(\d{1,3}(?:\.\d{1,3}){0,3})\s*(?:[.)\-–—:]|\s)")
    return [match.group(1) for match in expression.finditer(text)]


def validate_manifest(rows: list[dict[str, Any]], require_complete: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    counts = Counter(str(row.get("category", "")) for row in rows)
    for index, row in enumerate(rows, 1):
        if row.get("category") not in CATEGORIES:
            errors.append(f"Fila {index}: category inválida.")
        if not str(row.get("pdf", "")).strip() or int(row.get("page", 0) or 0) < 1:
            errors.append(f"Fila {index}: pdf/page inválido.")
        if row.get("ground_truth_status") != "verified":
            errors.append(f"Fila {index}: ground truth no verificado.")
        if not isinstance(row.get("text"), str) or not isinstance(row.get("numerals"), list):
            errors.append(f"Fila {index}: text/numerals requieren tipos válidos.")
    if require_complete:
        for category, minimum in REQUIRED_COUNTS.items():
            if counts[category] < minimum:
                errors.append(f"{category}: {counts[category]}/{minimum} casos.")
    return {"valid": not errors, "errors": errors, "distribution": dict(counts), "cases": len(rows)}


def _metrics(bucket: dict[str, float]) -> dict[str, float]:
    precision = bucket["tp"] / max(1, bucket["tp"] + bucket["fp"])
    recall = bucket["tp"] / max(1, bucket["tp"] + bucket["fn"])
    return {
        "character_error_rate": round(bucket["edits"] / max(1, bucket["chars"]), 4),
        "character_accuracy": round(max(0.0, 1 - bucket["edits"] / max(1, bucket["chars"])), 4),
        "numeral_precision": round(precision, 4),
        "numeral_recall": round(recall, 4),
        "numeral_f1": round(2 * precision * recall / max(1e-9, precision + recall), 4),
        "table_recall": round(bucket["tables_found"] / max(1, bucket["tables_expected"]), 4),
        "review_rate": round(bucket["review"] / max(1, bucket["cases"]), 4),
        "seconds_per_page": round(bucket["seconds"] / max(1, bucket["cases"]), 2),
        "cases": int(bucket["cases"]),
    }


def run_benchmark(manifest: Path, output: Path, require_complete: bool = True) -> dict[str, Any]:
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    validation = validate_manifest(rows, require_complete=require_complete)
    if not validation["valid"]:
        raise ValueError("Manifest inválido: " + " ".join(validation["errors"]))
    base = manifest.parent
    totals: dict[str, float] = defaultdict(float)
    categories: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    details: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temporary:
        engine = OCREngine(Path(temporary) / "cache")
        for case_number, row in enumerate(rows, 1):
            pdf_path = (base / row["pdf"]).resolve()
            page_index = int(row["page"]) - 1
            category = row["category"]
            with pymupdf.open(pdf_path) as document:
                page = document[page_index]
                started = time.perf_counter()
                if category == "digital":
                    actual_text = page.get_text("text")
                    actual_numerals = set(native_numerals(actual_text))
                    tables = 0
                    review = False
                    route = "pymupdf_native"
                else:
                    dpi = ocr_dpi_for_page(page.rect.width, page.rect.height)
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False)
                    image = Path(temporary) / f"case-{case_number}.png"
                    pixmap.save(image)
                    result = engine.run(image, force=True)
                    actual_text = str(result.get("text", ""))
                    actual_numerals = {str(item["numeral"]) for item in result.get("numerals", [])}
                    tables = len(result.get("tables", []))
                    review = bool(result.get("requires_review"))
                    route = "paddleocr"
                elapsed = time.perf_counter() - started
            expected_text = str(row["text"])
            expected_numerals = set(map(str, row["numerals"]))
            values = {
                "cases": 1, "chars": max(1, len(expected_text)),
                "edits": edit_distance(expected_text, actual_text),
                "tp": len(expected_numerals & actual_numerals),
                "fp": len(actual_numerals - expected_numerals),
                "fn": len(expected_numerals - actual_numerals),
                "tables_expected": max(0, int(row.get("expected_tables", 0))),
                "tables_found": min(tables, max(0, int(row.get("expected_tables", 0)))),
                "review": int(review), "seconds": elapsed,
            }
            for key, value in values.items():
                totals[key] += value; categories[category][key] += value
            details.append({
                "case": case_number, "category": category, "page": page_index + 1,
                "route": route, "character_error_rate": round(values["edits"] / values["chars"], 4),
                "expected_numerals": sorted(expected_numerals), "detected_numerals": sorted(actual_numerals),
                "expected_tables": int(values["tables_expected"]), "detected_tables": tables,
                "requires_review": review, "seconds": round(elapsed, 2),
            })
    metrics = _metrics(totals)
    by_category = {name: _metrics(categories[name]) for name in CATEGORIES}
    gates = {
        "dataset_complete": validation["valid"],
        "numerals": metrics["numeral_recall"] >= 0.985,
        "bad_copies": by_category["scanned_bad"]["character_accuracy"] >= 0.88,
        "tables": metrics["table_recall"] >= 0.95,
        "review_rate": metrics["review_rate"] <= 0.05,
        "time": metrics["seconds_per_page"] <= 60,
        "no_fallback": all(item["route"] in {"pymupdf_native", "paddleocr"} for item in details),
    }
    report = {
        "schema_version": "2.0.0", "manifest": validation, "metrics": metrics,
        "by_category": by_category, "gates": gates, "promotable": all(gates.values()),
        "details": details,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark OCR constitucional")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("ocr_benchmark_report.json"))
    parser.add_argument("--pilot", action="store_true", help="Permite menos de 40 casos; nunca habilita promoción.")
    arguments = parser.parse_args()
    report = run_benchmark(arguments.manifest, arguments.output, require_complete=not arguments.pilot)
    if arguments.pilot:
        report["promotable"] = False
        report["gates"]["dataset_complete"] = False
        arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": report["metrics"], "gates": report["gates"], "promotable": report["promotable"]}, ensure_ascii=False, indent=2))
    return 0 if report["promotable"] or arguments.pilot else 2

