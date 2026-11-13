"""Motor OCR local, trazable y compatible con FiscalOps."""

from .engine import PaddleOCREngine
from .numerals import detect_numerals, normalize_numeral

__all__ = ["PaddleOCREngine", "detect_numerals", "normalize_numeral"]
