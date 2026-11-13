"""Public adapter for FiscalOps local OCR."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from paddle_ocr_engine.engine import PaddleOCREngine


class OCREngine:
    """API estable de FiscalOps respaldada exclusivamente por PaddleOCR local."""

    def __init__(self, cache_dir: Path, lang: str = "spa", model_dir: Path | None = None) -> None:
        self._engine = PaddleOCREngine(cache_dir, model_dir=model_dir, lang=lang)

    def available(self) -> dict[str, Any]:
        status = self._engine.available()
        return {
            "primary": "paddleocr" if status.get("available") else "none",
            "paddle": status,
            "tesseract": {"available": False, "disabled": True},
            "gpu": False,
            "mkldnn": True,
            "fallback": False,
        }

    def is_usable(self) -> bool:
        return self._engine.is_usable()

    def run(self, image_path: Path, force: bool = False, psm: int | None = None) -> dict[str, Any]:
        return self._engine.run(image_path, force=force, psm=psm)

    def read_region(self, image_path: Path) -> dict[str, Any]:
        return self._engine.read_region(image_path)
