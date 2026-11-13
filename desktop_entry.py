"""Offline entry point used by the Windows executable."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def configure_paths(root: Path) -> Path:
    # Only release folders have this marker. Existing workspaces keep their paths.
    if (root / "portable.flag").is_file():
        os.environ.setdefault("FISCALOPS_DATA_DIR", str(root / "datos_usuario"))
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(root / "models" / "paddleocr" / "v3-cache")
    from config import DATA_ROOT
    return DATA_ROOT


def check_installation(root: Path) -> int:
    import bootstrap
    result = bootstrap.main()  # --check is present: never installs or downloads.
    if result:
        return result
    from paddle_ocr_engine.modern import LAYOUT_MODEL, TEXT_MODELS, model_path, model_ready
    model_root = root / "models" / "paddleocr"
    missing = [name for name in (*TEXT_MODELS.values(), LAYOUT_MODEL)
               if not model_ready(model_path(model_root, name))]
    if missing:
        print("[ERROR] Modelos OCR incompletos: " + ", ".join(missing))
        return 1
    for filename in ("static/index.html", "static/audit.html", "runtime/python.exe"):
        if not (root / filename).is_file():
            print(f"[ERROR] Archivo necesario ausente: {filename}")
            return 1
    if (root / "portable.flag").is_file():
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel.GetModuleHandleW.restype = wintypes.HMODULE
        kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        kernel.GetModuleFileNameW.restype = wintypes.DWORD
        for name in ("msvcp140.dll", "vcomp140.dll"):
            library = root / "runtime" / name
            handle = kernel.GetModuleHandleW(name)
            loaded = ctypes.create_unicode_buffer(4096)
            if not library.is_file() or not handle or not kernel.GetModuleFileNameW(handle, loaded, len(loaded)):
                print(f"[ERROR] Biblioteca nativa portable ausente: {name}")
                return 1
            if Path(loaded.value).resolve().parent != (root / "runtime").resolve():
                print(f"[ERROR] {name} se cargó fuera del runtime portable: {loaded.value}")
                return 1
        print("[OK] Bibliotecas nativas cargadas desde el runtime portable.")
    print("[OK] Runtime, interfaz y modelos OCR locales completos.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="FiscalOps para Windows")
    parser.add_argument("--check", action="store_true", help="Verifica sin instalar ni descargar")
    parser.add_argument("--no-browser", action="store_true", help="Inicia sin abrir el navegador")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    data_root = configure_paths(root)
    if args.check:
        return check_installation(root)
    try:
        data_root.mkdir(parents=True, exist_ok=True)
        # Test actual write permission before importing the application.
        import tempfile
        with tempfile.TemporaryFile(dir=data_root):
            pass
    except OSError as error:
        print(f"[ERROR] No se puede escribir en {data_root}: {error}")
        print("Extraiga el programa en una carpeta con permiso de escritura.")
        return 1
    if args.no_browser:
        os.environ["FISCALOPS_NO_BROWSER"] = "1"
    print(f"Expedientes y respaldos de trabajo: {data_root}", flush=True)
    from launcher import main as launch
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
