"""PaddleOCR 3 adapter for the local CPU pipeline on Python 3.12 and 3.13."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any

from .preprocessor import load_image
from .schema import confidence01, polygon_bbox

TEXT_MODELS = {
    "text_detection": "PP-OCRv5_mobile_det",
    "text_recognition": "latin_PP-OCRv5_mobile_rec",
    "textline_orientation": "PP-LCNet_x0_25_textline_ori",
}
LAYOUT_MODEL = "PP-DocLayout-S"


def configure(model_dir: Path) -> None:
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(model_dir / "v3-cache"))
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")


def model_path(model_dir: Path, name: str) -> Path:
    return model_dir / "v3" / name


def model_ready(path: Path) -> bool:
    return all((path / name).is_file() for name in ("inference.json", "inference.pdiparams", "inference.yml"))


def install_models(model_dir: Path) -> None:
    configure(model_dir)
    from paddlex.inference.utils.official_models import official_models

    for name in (*TEXT_MODELS.values(), LAYOUT_MODEL):
        destination = model_path(model_dir, name)
        if model_ready(destination):
            continue
        source = Path(official_models[name])
        shutil.copytree(source, destination, dirs_exist_ok=True)
        if not model_ready(destination):
            raise RuntimeError(f"No se pudo verificar el modelo {name}.")


class ModernOCR:
    def __init__(self, model_dir: Path):
        configure(model_dir)
        from paddleocr import PaddleOCR

        paths = {}
        for role, name in TEXT_MODELS.items():
            paths[role + "_model_name"] = name
            paths[role + "_model_dir"] = str(model_path(model_dir, name))
        self.engine = PaddleOCR(
            device="cpu", cpu_threads=min(4, os.cpu_count() or 1),
            enable_mkldnn=True, use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=True, text_recognition_batch_size=1,
            textline_orientation_batch_size=1, text_det_limit_side_len=1536,
            text_det_limit_type="max", **paths,
        )

    def ocr(self, image, *, cls=True):
        del cls
        lines = []
        for result in self.engine.predict(image):
            for polygon, text, score in zip(result["rec_polys"], result["rec_texts"], result["rec_scores"]):
                lines.append([polygon.tolist(), (text, float(score))])
        return [lines]


class ModernLayoutAnalyzer:
    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.engine: Any = None

    def models_ready(self) -> bool:
        return model_ready(model_path(self.model_dir, LAYOUT_MODEL))

    def analyze(self, image_path: Path) -> dict:
        if self.engine is None:
            configure(self.model_dir)
            from paddleocr import LayoutDetection

            self.engine = LayoutDetection(
                model_name=LAYOUT_MODEL, model_dir=str(model_path(self.model_dir, LAYOUT_MODEL)),
                device="cpu", cpu_threads=min(4, os.cpu_count() or 1), enable_mkldnn=True,
            )
        image = load_image(image_path)
        regions, tables = [], []
        for result in self.engine.predict(image, batch_size=1):
            for box in result["boxes"]:
                kind = str(box["label"]).lower()
                bbox = polygon_bbox(box["coordinate"])
                score = confidence01(box["score"])
                if kind in {"image", "figure", "chart"}:
                    kind = "figure"
                regions.append({"id": f"layout-{len(regions) + 1:03d}", "type": kind, "bbox": bbox, "confidence": score})
                if kind == "table":
                    tables.append({"table_id": f"table-{len(tables) + 1:03d}", "bbox": bbox, "confidence": score})
        height, width = image.shape[:2]
        return {"regions": regions, "tables": tables, "size": [width, height]}
