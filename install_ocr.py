from __future__ import annotations

import json
import sys
from pathlib import Path

from paddle_ocr_engine.engine import PaddleOCREngine


def main() -> int:
    if not (3, 10) <= sys.version_info[:2] <= (3, 13):
        print(f"[ERROR] Use Python 3.10 a 3.13 x64; se detectó {sys.version.split()[0]}.")
        return 2
    root = Path(__file__).resolve().parent
    engine = PaddleOCREngine(root / "work" / "ocr_cache", root / "models" / "paddleocr")
    print("Descargando y verificando modelos PaddleOCR en models/paddleocr...")
    status = engine.install_models()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    print("[OK] Modelos disponibles. Después de este paso FiscalOps funciona sin red.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
