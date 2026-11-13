"""Prepare the official, self-contained Python 3.13.14 Windows runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import urllib.request
from zipfile import ZipFile

PYTHON_URL = "https://www.python.org/ftp/python/3.13.14/python-3.13.14-embed-amd64.zip"
PYTHON_SHA256 = "90b4e5b9898b72d744650524bff92377c367f44bd5fbd09e3148656c080ad907"


def download(url: str, destination: Path, checksum: str) -> None:
    with urllib.request.urlopen(url, timeout=120) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != checksum:
        raise ValueError("La descarga no coincide con su SHA-256 oficial.")


def unpack(archive: Path, target: Path) -> None:
    with ZipFile(archive) as package:
        for entry in package.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename:
                raise ValueError("La descarga contiene una ruta inválida.")
        package.extractall(target)


def main() -> None:
    root = Path(__file__).resolve().parent
    destination = root / "runtime"
    if destination.exists():
        raise ValueError("Ya existe runtime. Usa PORTABLE_RUN.bat --check para comprobarlo.")
    with tempfile.TemporaryDirectory(prefix="python313-", dir=root) as temporary:
        staging = Path(temporary)
        runtime = staging / "runtime"
        download(PYTHON_URL, staging / "python.zip", PYTHON_SHA256)
        unpack(staging / "python.zip", runtime)
        (runtime / "python313._pth").write_text(
            "python313.zip\n.\nLib/site-packages\n..\nimport site\n", encoding="utf-8")
        metadata_url = "https://pypi.org/pypi/pip/25.3/json"
        with urllib.request.urlopen(metadata_url, timeout=30) as response:
            metadata = json.load(response)
        wheel = next(file for file in metadata["urls"] if file["filename"].endswith(".whl"))
        download(wheel["url"], staging / "pip.whl", wheel["digests"]["sha256"])
        unpack(staging / "pip.whl", runtime / "Lib" / "site-packages")
        runtime.rename(destination)
    print("Python 3.13.14 x64 preparado en runtime. Ejecuta run.bat para instalar las dependencias.")


if __name__ == "__main__":
    main()
