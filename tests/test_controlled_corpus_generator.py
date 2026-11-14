from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from document_inspector import inspect_pdf


def _generator_module():
    path = Path(__file__).parent / "ocr_dataset" / "generate_controlled_corpus.py"
    spec = importlib.util.spec_from_file_location("controlled_corpus_generator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_controlled_corpus_is_synthetic_and_covers_routes(tmp_path):
    module = _generator_module()
    result = module.generate_corpus(tmp_path / "corpus", per_category=1)
    assert result["synthetic_only"] is True
    assert {row["category"] for row in result["rows"]} >= {"digital", "scanned_good", "scanned_regular", "scanned_bad", "mixed", "multipage"}
    assert all(row["ground_truth_status"] == "verified" for row in result["rows"])
    assert json.loads((tmp_path / "corpus" / "corpus_metadata.json").read_text(encoding="utf-8"))["synthetic_only"] is True
    classifications = {
        row["category"]: inspect_pdf(tmp_path / "corpus" / row["pdf"])["pages"][row["page"] - 1]["page_type"]
        for row in result["rows"] if row["category"] in {"digital", "scanned_good", "mixed"}
    }
    assert classifications["digital"] == "DIGITAL_TEXT"
    assert classifications["scanned_good"] == "SCANNED_IMAGE"
    assert classifications["mixed"] == "MIXED_CONTENT"
