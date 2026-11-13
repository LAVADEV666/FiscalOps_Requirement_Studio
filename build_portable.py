"""Prepare a movable Windows CPython runtime for FiscalOps."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


def build_runtime(destination: Path) -> None:
    if sys.platform != "win32" or struct.calcsize("P") != 8 or not (3, 10) <= sys.version_info[:2] <= (3, 13):
        raise ValueError("Se requiere CPython 3.10 a 3.13 para Windows x64.")
    if destination.exists():
        raise ValueError(f"Ya existe {destination}. Mueva esa carpeta antes de preparar otra distribución.")
    base = Path(sys.base_prefix)
    requirements = Path(__file__).resolve().parent / "requirements.txt"
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary) / "runtime"
        stage.mkdir()
        for source in [base / "python.exe", base / "LICENSE.txt", *base.glob("*.dll"), *base.glob("*.pyd"), *base.glob("python*.zip")]:
            shutil.copy2(source, stage / source.name)
        for name in ("DLLs", "Lib"):
            if not (base / name).is_dir():
                continue
            shutil.copytree(base / name, stage / name, ignore=shutil.ignore_patterns(
                "site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter",
            ))
        module = f"python{sys.version_info.major}{sys.version_info.minor}"
        (stage / f"{module}._pth").write_text(f".\n{module}.zip\nDLLs\nLib\nLib\\site-packages\n..\nimport site\n", encoding="ascii")
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
            "--target", str(stage / "Lib" / "site-packages"), "-r", str(requirements),
        ], check=True)
        subprocess.run([str(stage / "python.exe"), "-B", "-c",
                        "import fastapi, uvicorn, docx, pymupdf, pdfplumber, cv2, PIL, paddle, paddleocr"],
                       cwd=stage, check=True)
        stage.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parent / "runtime")
    args = parser.parse_args()
    try:
        build_runtime(args.destination.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"[ERROR] {error}\n")
