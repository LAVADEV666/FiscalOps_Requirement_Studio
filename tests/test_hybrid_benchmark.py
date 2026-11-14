from __future__ import annotations

import json

from reportlab.pdfgen import canvas

from hybrid_benchmark import run_benchmark


def test_hybrid_benchmark_measures_verified_native_case(tmp_path):
    pdf = tmp_path / "digital.pdf"
    document = canvas.Canvas(str(pdf))
    document.drawString(40, 760, "Texto validado de prueba")
    document.save()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"pdf": pdf.name, "page": 1, "text": "Texto validado de prueba", "ground_truth_status": "verified"}) + "\n", encoding="utf-8")
    output = tmp_path / "report.json"
    report = run_benchmark(manifest, output)
    assert report["metrics"]["measured_cases"] == 1
    assert report["metrics"]["cer"] == 0
    assert report["promotable"] is True
    assert report["quality_gates"]["cer_target_99"] is True
    assert report["quality_gates"]["no_ocr_errors"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["stages"]["paddleocr"]["status"] == "NOT_RUN"
