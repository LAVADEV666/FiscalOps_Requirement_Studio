"""Build a clean Windows x64 portable ZIP with a native EXE launcher.

No downloads, package installation, or copying of operational data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from config import VERSION

ROOT = Path(__file__).resolve().parent
RELEASE_NAME = f"FiscalOps-{VERSION}-Windows-x64-Portable"
APP_MODULES = (
    "ai_engine", "ai_review_engine", "app", "audit_engine", "bootstrap",
    "compliance_engine", "config", "core", "desktop_entry", "document_model",
    "enterprise_store", "evidence_manager", "job_manager", "launcher",
    "maintenance", "manual_ocr", "ocr_engine", "persistence", "processing_pipeline",
    "template_store", "text_normalizer", "visual_assets", "word_audit",
    "word_builder", "workspace_backup", "professional_document", "backup_store",
)
MODELS = (
    "PP-OCRv5_mobile_det", "latin_PP-OCRv5_mobile_rec",
    "PP-LCNet_x0_25_textline_ori", "PP-DocLayout-S",
)
IGNORED = {"__pycache__", ".pytest_cache", ".git", ".DS_Store"}
NATIVE_RUNTIME = ("msvcp140.dll", "vcomp140.dll")
GUIDE = """FISCALOPS REQUIREMENT STUDIO 8.0.1 - WINDOWS x64 PORTABLE

1. Use Windows 10/11 de 64 bits.
2. Extraiga TODO el ZIP a una carpeta donde pueda escribir (p. ej. Documentos).
3. Abra FiscalOps.exe. No necesita instalar Python, Office ni paquetes.
4. Espere a que se abra el navegador en http://127.0.0.1:6969.
   Mantenga abierta la ventana de FiscalOps mientras trabaja.
5. Para salir, use el boton de cerrar de la aplicacion o Ctrl+C en la consola.
   Cerrar solo la pestana del navegador no detiene el programa.

El EXE necesita las carpetas runtime, static y models que vienen en el ZIP.
No ejecute el EXE desde dentro del ZIP ni lo copie solo.
El runtime y los cuatro modelos OCR estan incluidos; no se descargan al abrir.
Las bibliotecas nativas x64 del OCR se incluyen junto a Python en runtime.
WordCraft, la interfaz SSGT y sus recursos se incluyen para trabajar sin conexion.
El primer uso de OCR puede tardar mientras se cargan los modelos en memoria.
La IA opcional de Ollama/Donut y sus modelos se instalan por separado.

DATOS Y TRASLADO
Los expedientes nuevos se guardan en datos_usuario junto al EXE.
Para trasladar la aplicacion CON sus expedientes, cierre FiscalOps y copie toda
la carpeta, incluyendo datos_usuario. Respalde esa carpeta antes de borrar o
reemplazar el programa. Para actualizar, extraiga el nuevo ZIP por separado y
copie datos_usuario con ambas versiones cerradas.
Puede elegir otra ruta definiendo FISCALOPS_DATA_DIR antes de abrir el EXE.
El ZIP de distribucion no incluye expedientes, RFC, plantillas ni documentos
personales del equipo donde se genero.

DIAGNOSTICO
Abra una terminal en esta carpeta y ejecute: .\\FiscalOps.exe --check
El registro se guarda en datos_usuario\\app.log (o en la ruta configurada).
Si el puerto 6969 esta ocupado por FiscalOps, se abre la instancia existente.
Si esta ocupado por otro programa, se muestra el error sin detener ese programa.
"""


def include_file(path: Path) -> bool:
    return not any(part in IGNORED for part in path.parts) and path.suffix not in {".pyc", ".pyo", ".log"}


def copy_tree(source: Path, destination: Path) -> None:
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if item.is_file() and include_file(relative):
            if not item.resolve().is_relative_to(source.resolve()):
                raise ValueError(f"Enlace fuera del paquete: {item}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def compile_launcher(output: Path) -> None:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    compiler = windows / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not compiler.is_file():
        raise ValueError("Se necesita el compilador de .NET Framework incluido en Windows x64.")
    subprocess.run([
        str(compiler), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
        f"/out:{output}", str(ROOT / "packaging" / "FiscalOpsLauncher.cs"),
    ], check=True)


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def bundle_native_runtime(destination: Path, system_directory: Path | None = None) -> None:
    """Ship the two v14 native dependencies that otherwise fall back to System32."""
    system_directory = system_directory or Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
    entries = []
    for name in NATIVE_RUNTIME:
        source = ROOT / "runtime" / name
        if not source.is_file():
            source = system_directory / name
        if not source.is_file():
            raise ValueError(f"Falta {name} x64 para preparar el runtime portable.")
        with source.open("rb") as library:
            if library.read(2) != b"MZ":
                raise ValueError(f"Biblioteca nativa inválida: {name}")
            library.seek(0x3C)
            header = library.read(4)
            if len(header) != 4:
                raise ValueError(f"Biblioteca nativa incompleta: {name}")
            offset = struct.unpack("<I", header)[0]
            library.seek(offset)
            if library.read(6) != b"PE\0\0\x64\x86":
                raise ValueError(f"Se requiere la biblioteca x64: {name}")
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        entries.append({"name": name, "sha256": digest(target)})
    (destination / "NATIVE_RUNTIME.json").write_text(json.dumps({
        "provider": "Microsoft Corporation", "architecture": "x64", "files": entries,
        "deployment": "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files",
    }, indent=2), encoding="utf-8")
    (destination / "NOTICE-MSVC.txt").write_text(
        "Microsoft Visual C++ Runtime files (x64)\nCopyright Microsoft Corporation.\n"
        "Unmodified runtime files for the native application dependencies.\n"
        "Deployment: https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files\n"
        "Terms: https://learn.microsoft.com/visualstudio/releases/2026/redistribution\n",
        encoding="utf-8",
    )


def write_manifest(folder: Path) -> None:
    files = [path for path in sorted(folder.rglob("*")) if path.is_file() and path != folder / "MANIFEST.json"]
    manifest = {"version": VERSION, "platform": "Windows-x64", "files": [
        {"path": path.relative_to(folder).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in files
    ]}
    (folder / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_archive(folder: Path, output: Path) -> None:
    if output.resolve().is_relative_to(folder.resolve()):
        raise ValueError("El ZIP debe guardarse fuera de la carpeta que contiene el programa.")
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=6) as package:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                package.write(path, path.relative_to(folder.parent).as_posix())


def build(destination: Path) -> Path:
    if sys.platform != "win32" or sys.version_info[:2] != (3, 13):
        raise ValueError("Ejecute con runtime\\python.exe (Python 3.13 para Windows x64).")
    destination = destination.resolve()
    folder = destination / RELEASE_NAME
    archive = destination / f"{RELEASE_NAME}.zip"
    if folder.exists() or archive.exists():
        raise ValueError(f"Ya existe una distribución en {destination}. Elija otro --output.")
    for name in MODELS:
        for filename in ("inference.json", "inference.pdiparams", "inference.yml"):
            if not (ROOT / "models" / "paddleocr" / "v3" / name / filename).is_file():
                raise ValueError(f"Falta el modelo {name}/{filename}. Prepare el OCR primero.")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fiscalops-build-", dir=destination) as temporary:
        stage = Path(temporary) / RELEASE_NAME
        stage.mkdir()
        print("[1/5] Compilando FiscalOps.exe...", flush=True)
        compile_launcher(stage / "FiscalOps.exe")
        print("[2/5] Copiando programa y runtime independientes...", flush=True)
        for module in APP_MODULES:
            shutil.copy2(ROOT / f"{module}.py", stage)
        copy_tree(ROOT / "static", stage / "static")
        copy_tree(ROOT / "paddle_ocr_engine", stage / "paddle_ocr_engine")
        copy_tree(ROOT / "runtime", stage / "runtime")
        bundle_native_runtime(stage / "runtime")
        for name in MODELS:
            source = ROOT / "models" / "paddleocr" / "v3" / name
            copy_tree(source, stage / "models" / "paddleocr" / "v3" / name)
        (stage / "portable.flag").write_text("Datos junto al programa.\n", encoding="utf-8")
        (stage / "LEEME.txt").write_text(GUIDE, encoding="utf-8")
        print("[3/5] Verificando desde la carpeta nueva...", flush=True)
        subprocess.run([str(stage / "FiscalOps.exe"), "--check"], cwd=stage, check=True)
        # Imports can create an empty model cache, but no operational data is shipped.
        for name in ("datos_usuario", "work", "data", "corrections_store"):
            if (stage / name).exists():
                raise ValueError(f"La verificación dejó datos de operación: {name}")
        write_manifest(stage)
        print("[4/5] Comprimiendo ZIP portable...", flush=True)
        staged_zip = Path(temporary) / archive.name
        write_archive(stage, staged_zip)
        print("[5/5] Comprobando integridad del ZIP...", flush=True)
        with ZipFile(staged_zip) as package:
            bad = package.testzip()
            if bad:
                raise ValueError(f"Archivo corrupto en ZIP: {bad}")
        checksum = digest(staged_zip)
        stage.rename(folder)
        staged_zip.rename(archive)
        (destination / f"{archive.name}.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
        shutil.copy2(folder / "FiscalOps.exe", ROOT / "FiscalOps.exe")
    print(f"[OK] {archive} ({archive.stat().st_size / 1024**2:.1f} MiB)", flush=True)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        build(args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"[ERROR] {error}\n")
