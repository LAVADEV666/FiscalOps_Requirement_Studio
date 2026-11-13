from __future__ import annotations

import importlib
import importlib.metadata
import os
from pathlib import Path
import struct
import subprocess
import sys
import sysconfig


def main() -> int:
    if (not (3, 10) <= sys.version_info[:2] <= (3, 13)
            or struct.calcsize("P") != 8 or sysconfig.get_config_var("Py_GIL_DISABLED")):
        print(f"[ERROR] Se requiere Python 3.10 a 3.13 x64 estándar. Detectado {sys.version.split()[0]}.")
        return 2
    modern = sys.version_info[:2] >= (3, 12)
    expected = {"paddlepaddle": "3.2.2", "paddleocr": "3.3.2", "paddlex": "3.3.12"} if modern else {
        "paddlepaddle": "2.6.2", "paddleocr": "2.9.1",
    }
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(Path(__file__).resolve().parent / "models" / "paddleocr" / "v3-cache"))
    modules = ("fastapi", "uvicorn", "multipart", "docx", "pdfplumber", "pymupdf", "cv2",
               "PIL", "paddle", "paddleocr", "reportlab")
    issues = []
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception as error:
            issues.append(f"{module} ({type(error).__name__})")
    for package, version in expected.items():
        try:
            if importlib.metadata.version(package) != version:
                issues.append(f"{package} requiere {version}")
        except importlib.metadata.PackageNotFoundError:
            issues.append(f"{package} requiere {version}")
    if not issues:
        print(f"[OK] Python {sys.version.split()[0]} y dependencias verificados.")
        return 0
    print("Dependencias por preparar. " + ", ".join(issues))
    if "--check" in sys.argv:
        return 1
    requirements = Path(__file__).resolve().parent / "requirements.txt"
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                             "--no-compile", "-r", str(requirements)])
    if result.returncode:
        return result.returncode
    return subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--check"]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
