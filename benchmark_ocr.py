"""Benchmark local de OCR contra un manifest JSONL anonimizado.

Cada línea: {"pdf":"ruta.pdf","page":1,"text":"...","numerals":["1","1.1"]}
No envía datos ni guarda el texto reconocido fuera del directorio temporal.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import fitz

from config import ocr_dpi_for_page

from ocr_engine import OCREngine


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("ocr_benchmark_report.json"))
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit("El manifest no contiene casos.")
    base = args.manifest.parent
    totals = {"chars": 0, "edits": 0, "tp": 0, "fp": 0, "fn": 0, "review": 0, "seconds": 0.0}
    details = []
    with tempfile.TemporaryDirectory() as temp:
        engine = OCREngine(Path(temp) / "cache")
        for index, row in enumerate(rows, 1):
            pdf_path = (base / row["pdf"]).resolve()
            with fitz.open(pdf_path) as doc:
                page_index = int(row.get("page", 1)) - 1
                page = doc[page_index]
                dpi = ocr_dpi_for_page(page.rect.width, page.rect.height)
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                image = Path(temp) / f"case-{index}.png"
                pix.save(image)
            start = time.perf_counter(); result = engine.run(image, force=True); elapsed = time.perf_counter() - start
            expected_text = str(row.get("text", "")); actual_text = result.get("text", "")
            edits = edit_distance(expected_text, actual_text); totals["edits"] += edits; totals["chars"] += max(1, len(expected_text))
            expected = set(map(str, row.get("numerals", []))); actual = {str(x["numeral"]) for x in result.get("numerals", [])}
            totals["tp"] += len(expected & actual); totals["fp"] += len(actual - expected); totals["fn"] += len(expected - actual)
            totals["review"] += int(bool(result.get("requires_review"))); totals["seconds"] += elapsed
            details.append({"case": index, "page": page_index + 1, "cer": round(edits / max(1, len(expected_text)), 4), "expected_numerals": sorted(expected), "detected_numerals": sorted(actual), "seconds": round(elapsed, 2)})
    precision = totals["tp"] / max(1, totals["tp"] + totals["fp"]); recall = totals["tp"] / max(1, totals["tp"] + totals["fn"])
    report = {"schema_version": "1.0.0", "cases": len(rows), "metrics": {"cer": round(totals["edits"] / totals["chars"], 4), "numeral_precision": round(precision, 4), "numeral_recall": round(recall, 4), "numeral_f1": round(2 * precision * recall / max(1e-9, precision + recall), 4), "review_rate": round(totals["review"] / len(rows), 4), "seconds_per_page": round(totals["seconds"] / len(rows), 2)}, "details": details}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from paddle_ocr_engine.benchmark import main as constitutional_main
    raise SystemExit(constitutional_main())
