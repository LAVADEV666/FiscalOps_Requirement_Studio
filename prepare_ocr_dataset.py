"""Genera un inventario de anotación sin copiar PDFs ni datos fuera del equipo."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Preparar manifest OCR para anotación manual")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tests/ocr_dataset/local/manifest.template.jsonl"))
    parser.add_argument("--max-pages", type=int, default=1)
    arguments = parser.parse_args()
    rows = []
    for pdf in sorted(arguments.source.glob("*.pdf")):
        with pymupdf.open(pdf) as document:
            for page_number, page in enumerate(document, 1):
                if page_number > max(1, arguments.max_pages):
                    break
                native_text = page.get_text("text").strip()
                category = "digital" if len(native_text) >= 80 else "scanned_regular"
                rows.append({
                    "pdf": str(pdf.resolve()), "page": page_number, "category": category,
                    "text": native_text if category == "digital" else "", "numerals": [],
                    "expected_tables": 0, "ground_truth_status": "needs_manual_verification",
                    "anonymization_certified": False,
                })
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"documents": len({row['pdf'] for row in rows}), "cases": len(rows), "output": str(arguments.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
