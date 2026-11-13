from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .preprocessor import load_image
from .schema import confidence01, polygon_bbox

LAYOUT_MODELS = {
    "rec_model_dir": "whl/rec/en/en_PP-OCRv4_rec_infer",
    "det_model_dir": "whl/det/en/en_PP-OCRv3_det_infer",
    "table_model_dir": "whl/table/en_ppstructure_mobile_v2.0_SLANet_infer",
    "layout_model_dir": "whl/layout/picodet_lcnet_x1_0_fgd_layout_infer",
}


class LayoutAnalyzer:
    """PP-StructureV2 para regiones y tablas; no reemplaza el OCR principal."""

    def __init__(self, model_dir: Path, lang: str = "es") -> None:
        self.model_dir = Path(model_dir)
        self.lang = lang
        os.environ["PADDLE_OCR_BASE_DIR"] = str(self.model_dir.resolve())
        self._engine: Any = None

    def models_ready(self) -> bool:
        return all((self.model_dir / folder / name).is_file()
                   for folder in LAYOUT_MODELS.values() for name in ("inference.pdmodel", "inference.pdiparams"))

    def _ensure(self) -> None:
        if self._engine is not None:
            return
        from paddleocr import PPStructure
        paths = {key: str(self.model_dir / folder) for key, folder in LAYOUT_MODELS.items()}
        # PaddleOCR 2.10 intenta descargar un modelo Latex aun con
        # ``formula=False``. Se apunta ese parámetro a un modelo local válido;
        # nunca se instancia porque la función de fórmulas está deshabilitada.
        self._engine = PPStructure(
            show_log=False,
            use_gpu=False,
            lang=self.lang,
            structure_version="PP-StructureV2",
            layout=True,
            table=True,
            ocr=False,
            formula=False,
            image_orientation=False,
            use_mkldnn=True,
            cpu_threads=min(4, os.cpu_count() or 1),
            formula_model_dir=paths["rec_model_dir"],
            **paths,
        )

    def install_models(self) -> None:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._ensure()
        if not self.models_ready():
            raise RuntimeError("PP-StructureV2 no dejó modelos locales de layout y tablas.")

    def analyze(self, image_path: Path) -> dict[str, Any]:
        self._ensure()
        image = load_image(image_path)
        regions: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        for index, item in enumerate(self._engine(image, return_ocr_result_in_table=True) or [], 1):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type", "text")).lower()
            bbox = polygon_bbox(item.get("bbox", []))
            score = confidence01(item.get("score", 0))
            regions.append({"id": f"layout-{index:03d}", "type": kind, "bbox": bbox, "confidence": score})
            if kind == "table":
                result = item.get("res", {}) if isinstance(item.get("res"), dict) else {}
                tables.append({"table_id": f"table-{index:03d}", "bbox": bbox, "confidence": score, "html": str(result.get("html", "")), "cell_bbox": result.get("cell_bbox", [])})
        height, width = image.shape[:2]
        return {"regions": regions, "tables": tables, "size": [width, height]}
