from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import cv2
import numpy as np


def quality_metrics(image: np.ndarray) -> dict[str, Any]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    contrast = float(gray.std())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    if blur < 45 or contrast < 30:
        label = "baja"
    elif blur < 100 or contrast < 45:
        label = "media"
    else:
        label = "alta"
    return {"label": label, "contrast": round(contrast, 2), "sharpness": round(blur, 2), "brightness": round(brightness, 2)}


def estimate_skew(gray: np.ndarray) -> float:
    if max(gray.shape) > 1600:
        ratio = 1600 / max(gray.shape)
        height, width = gray.shape
        gray = cv2.resize(gray, (max(1, round(width * ratio)), max(1, round(height * ratio))), interpolation=cv2.INTER_AREA)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(binary)
    if coords is None or len(coords) < 100:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    angle = (angle + 45) % 90 - 45
    return round(angle, 2) if abs(angle) <= 12 else 0.0


def rotate_bound(image: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
    h, w = image.shape[:2]
    center = (w / 2, h / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(np.ceil(h * sin + w * cos)), int(np.ceil(h * cos + w * sin))
    matrix[0, 2] += new_w / 2 - center[0]
    matrix[1, 2] += new_h / 2 - center[1]
    rotated = cv2.warpAffine(image, matrix, (new_w, new_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated, cv2.invertAffineTransform(matrix)


def preprocess(image: np.ndarray, profile: str, angle: float) -> tuple[np.ndarray, np.ndarray | None]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    inverse = None
    if abs(angle) >= 0.2:
        gray, inverse = rotate_bound(gray, angle)
    if profile == "balanced":
        gray = cv2.bilateralFilter(gray, 7, 45, 45)
        return cv2.createCLAHE(2.0, (8, 8)).apply(gray), inverse
    gray = cv2.medianBlur(gray, 3)
    gray = cv2.bilateralFilter(gray, 9, 60, 60)
    enhanced = cv2.createCLAHE(2.5, (8, 8)).apply(gray)
    binary = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 13)
    return binary, inverse


def load_image(image_path: Path) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(image_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"No se pudo leer la imagen: {image_path}")
    return image


def build_variants(image_path: Path) -> tuple[Iterator[dict[str, Any]], dict[str, Any]]:
    image = load_image(image_path)
    quality = quality_metrics(image)
    h, w = image.shape[:2]

    def variants():
        yield {"profile": "original", "image": image, "skew": 0, "width": w, "height": h}
        angle = estimate_skew(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        for profile in ("balanced", "aggressive"):
            processed, inverse = preprocess(image, profile, angle)
            yield {"profile": profile, "image": cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR),
                   "skew": angle, "inverse": inverse, "width": w, "height": h}

    return variants(), quality
