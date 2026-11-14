from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from threading import RLock
from typing import Any

from persistence import PersistenceError, atomic_json
from .numerals import detect_numerals, sequence_warnings
from .layout_analyzer import LayoutAnalyzer
from .preprocessor import build_variants
from .schema import ENGINE_VERSION, SCHEMA_VERSION, make_block
from .modern import ModernLayoutAnalyzer, ModernOCR, TEXT_MODELS, configure, detection_limit_side_len, install_models, model_path, model_ready

LOGGER = logging.getLogger("fiscalops.paddle_ocr")
OCR_LOCK = RLock()
MODEL_PATHS = {
    "det_model_dir": "whl/det/en/en_PP-OCRv3_det_infer",
    "rec_model_dir": "whl/rec/latin/latin_PP-OCRv3_rec_infer",
    "cls_model_dir": "whl/cls/ch_ppocr_mobile_v2.0_cls_infer",
}


class PaddleOCREngine:
    """Local PaddleOCR CPU pipeline with a stable FiscalOps result format."""

    def __init__(self, cache_dir: Path, model_dir: Path | None = None, lang: str = "es") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir = Path(model_dir or Path(__file__).resolve().parents[1] / "models" / "paddleocr")
        self.lang = "es" if lang in {"spa", "es"} else lang
        self._modern = sys.version_info[:2] >= (3, 12)
        if self._modern:
            configure(self.model_dir)
        # Debe definirse antes de cualquier import de ``paddleocr``; el paquete
        # resuelve su directorio base en tiempo de importación.
        os.environ["PADDLE_OCR_BASE_DIR"] = str(self.model_dir.resolve())
        self._ocr: Any = None
        # PP-StructureV2 solo publica layout ``en``/``ch``. El modelo de
        # layout es geométrico; el reconocimiento del español sigue en Latin.
        self._layout = ModernLayoutAnalyzer(self.model_dir) if self._modern else LayoutAnalyzer(self.model_dir, "en")
        self._error = ""

    def _model_ready(self) -> bool:
        if self._modern:
            return all(model_ready(model_path(self.model_dir, name)) for name in TEXT_MODELS.values())
        return all((self.model_dir / folder / name).is_file()
                   for folder in MODEL_PATHS.values() for name in ("inference.pdmodel", "inference.pdiparams"))

    def _ensure(self) -> None:
        if self._ocr is not None:
            return
        if self._modern:
            try:
                self._ocr = ModernOCR(self.model_dir)
            except Exception as error:
                self._error = str(error)
                raise RuntimeError(f"No se pudo iniciar PaddleOCR local: {error}") from error
            return
        os.environ.setdefault("PADDLE_OCR_BASE_DIR", str(self.model_dir))
        os.environ.setdefault("FLAGS_use_mkldnn", "1")
        try:
            from paddleocr import PaddleOCR
            kwargs: dict[str, Any] = {
                "use_angle_cls": True,
                "lang": self.lang,
                "use_gpu": False,
                "use_mkldnn": True,
                "show_log": False,
                "rec_batch_num": 1,
                "cls_batch_num": 1,
                "cpu_threads": min(4, os.cpu_count() or 1),
                "det_limit_side_len": detection_limit_side_len(),
                "ocr_version": "PP-OCRv3",
                **{key: str(self.model_dir / folder) for key, folder in MODEL_PATHS.items()},
            }
            self._ocr = PaddleOCR(**kwargs)
        except Exception as exc:
            self._error = str(exc)
            raise RuntimeError(f"PaddleOCR local no está disponible: {exc}") from exc

    def available(self) -> dict[str, Any]:
        try:
            import paddle
            import paddleocr
            dependencies = True
            versions = {"paddle": getattr(paddle, "__version__", ""), "paddleocr": getattr(paddleocr, "__version__", "")}
        except Exception as exc:
            dependencies = False
            versions = {}
            self._error = str(exc)
        return {
            "available": dependencies and self._model_ready(),
            "engine": "paddleocr",
            "engine_version": ENGINE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "dependencies": dependencies,
            "models_local": self._model_ready(),
            "layout_models_local": self._layout.models_ready(),
            "model_dir": str(self.model_dir),
            "versions": versions,
            "gpu": False,
            "fallback": False,
            "error": self._error,
        }

    def is_usable(self) -> bool:
        status = self.available()
        return bool(status["dependencies"] and status["models_local"])

    def install_models(self) -> dict[str, Any]:
        """Descarga modelos durante instalación; runtime solo verifica archivos locales."""
        self.model_dir.mkdir(parents=True, exist_ok=True)
        if self._modern:
            install_models(self.model_dir)
        else:
            self._ensure()
            self._layout.install_models()
        status = self.available()
        if not status["models_local"]:
            raise RuntimeError(f"PaddleOCR se inicializó pero no dejó modelos verificables en {self.model_dir}")
        return status

    @staticmethod
    def _parse(raw: Any, page_file: str, width: int, height: int, inverse=None) -> dict[str, Any]:
        lines = raw[0] if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list) else raw
        blocks: list[dict[str, Any]] = []
        for item in lines or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            polygon, recognition = item[0], item[1]
            if not isinstance(recognition, (list, tuple)) or not recognition:
                continue
            text = str(recognition[0] or "").strip()
            if not text:
                continue
            if inverse is not None:
                polygon = [[min(width, max(0, inverse[0] @ (x, y, 1))),
                            min(height, max(0, inverse[1] @ (x, y, 1)))] for x, y in polygon]
            block = make_block(text, recognition[1] if len(recognition) > 1 else 0, polygon, block_id=f"ocr-{len(blocks)+1:04d}")
            blocks.append(block)
        blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
        scores = [b["confidence"] for b in blocks]
        confidence = round(sum(scores) / len(scores), 4) if scores else 0.0
        numerals = detect_numerals(blocks, width)
        return {
            "page_file": page_file,
            "text": "\n".join(b["text"] for b in blocks),
            "confidence": confidence,
            "text_blocks": blocks,
            "numerals": numerals,
            "warnings": sequence_warnings(numerals),
        }

    def _recognize(self, path: Path, thorough: bool) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.is_usable():
            raise RuntimeError("PaddleOCR local requiere sus dependencias y modelos. Ejecuta INSTALAR_OCR.bat para repararlo.")
        self._ensure()
        variants, quality = build_variants(path)
        candidates = []
        last_error = None
        for variant in variants:
            try:
                raw = self._ocr.ocr(variant["image"], cls=True)
            except (RuntimeError, ValueError) as error:
                last_error = error
                LOGGER.warning("Falló el perfil OCR %s (%s).", variant["profile"], type(error).__name__)
                continue
            parsed = self._parse(raw, path.name, variant["width"], variant["height"], variant.get("inverse"))
            parsed.update(preprocessing_profile=variant["profile"], skew=variant["skew"],
                          width=variant["width"], height=variant["height"])
            count = sum(char.isalnum() for char in parsed["text"])
            candidates.append((parsed, count))
            if (not thorough and variant["profile"] == "original" and quality["label"] == "alta"
                    and len(parsed["text_blocks"]) > 1 and parsed["confidence"] >= .93
                    and all(not b["requires_review"] for b in parsed["text_blocks"])):
                break
            if (variant["profile"] == "balanced" and len(candidates) == 2
                    and min(item[0]["confidence"] for item in candidates) >= .90
                    and min(item[1] for item in candidates) >= .70 * max(item[1] for item in candidates)):
                break
        if not candidates:
            raise RuntimeError("No se pudo ejecutar PaddleOCR sobre la imagen.") from last_error
        # The original is always tried. Confidence is weighted against text coverage
        # so that a high-confidence partial pass does not easily replace a fuller page.
        coverage = max(1, *(count for _, count in candidates))
        best = max(candidates, key=lambda pair: (
            pair[0]["confidence"] + .24 * pair[1] / coverage + min(.06, len(pair[0]["numerals"]) * .01), pair[1]
        ))[0]
        best["preprocessing_candidates"] = [
            {
                "profile": item.get("preprocessing_profile", ""),
                "confidence": item.get("confidence", 0.0),
                "characters": count,
                "blocks": len(item.get("text_blocks", [])),
                "skew": item.get("skew", 0.0),
            }
            for item, count in candidates
        ]
        return best, quality

    def read_region(self, image_path: Path) -> dict[str, Any]:
        with OCR_LOCK:
            best, _ = self._recognize(Path(image_path), thorough=True)
        return best

    def run(self, image_path: Path, force: bool = False, psm: int | None = None) -> dict[str, Any]:
        del psm  # Paddle does not use Tesseract page segmentation modes.
        path = Path(image_path)
        has_layout = self._layout.models_ready()
        digest = hashlib.sha256(path.read_bytes() + f"{ENGINE_VERSION}:{self.lang}:modern={self._modern}:layout={has_layout}".encode()).hexdigest()
        cache_path = self.cache_dir / f"{digest}.json"
        start = time.perf_counter()
        with OCR_LOCK:
            if cache_path.exists() and not force:
                try:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    return {**cached, "page_file": path.name, "cached": True}
                except (OSError, ValueError, TypeError):
                    LOGGER.warning("Se omitió una entrada de caché OCR ilegible.")
            best, quality = self._recognize(path, thorough=False)
            layout = {"regions": [], "tables": []}
            cacheable = True
            if has_layout:
                try:
                    layout = self._layout.analyze(path)
                except Exception as exc:
                    cacheable = False
                    LOGGER.warning("No se pudo analizar el diseño de la página (%s).", type(exc).__name__)
            result = {
                "schema_version": SCHEMA_VERSION,
                "engine_version": ENGINE_VERSION,
                **best,
                "quality": quality,
                "tables": layout["tables"],
                "layout_size": layout.get("size"),
                "regions": layout["regions"] or [{"id": "full_page", "type": "text", "bbox": [0, 0, best.get("width", 0), best.get("height", 0)], "confidence": best.get("confidence", 0), "words": len(best.get("text", "").split())}],
                "requires_review": (
                    best.get("confidence", 0) < 0.90
                    or any(x.get("requires_review") for x in best.get("text_blocks", []))
                    or any(x.get("requires_review") for x in best.get("numerals", []))
                    or bool(best.get("warnings"))
                ),
                "duration_ms": round((time.perf_counter() - start) * 1000),
                "cached": False,
                "orientation": 0,
                "psm": None,
            }
            if cacheable:
                try:
                    atomic_json(cache_path, result, backup=False)
                except PersistenceError:
                    LOGGER.warning("No se pudo guardar la caché OCR.")
            return result
