import pytest

from paddle_ocr_engine.benchmark import native_numerals, validate_manifest


def test_native_numerals_support_hierarchy():
    assert native_numerals("1. Primero\n1.2. Segundo\nTexto") == ["1", "1.2"]


def test_manifest_refuses_unverified_ground_truth():
    result = validate_manifest([{"pdf": "x.pdf", "page": 1, "category": "scanned_bad", "text": "x", "numerals": [], "ground_truth_status": "auto"}], require_complete=False)
    assert result["valid"] is False


def test_manifest_enforces_40_case_distribution():
    rows = []
    for category in ("digital", "scanned_good", "scanned_regular", "scanned_bad"):
        rows.extend({"pdf": f"{category}-{i}.pdf", "page": 1, "category": category, "text": "texto", "numerals": [], "ground_truth_status": "verified"} for i in range(10))
    result = validate_manifest(rows)
    assert result["valid"] is True and result["cases"] == 40
