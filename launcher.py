from __future__ import annotations
import logging
import json
import os
from logging.handlers import RotatingFileHandler
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from config import APP_NAME, VERSION, EDITION, HOST, PORT, DATA_ROOT
DATA_ROOT.mkdir(parents=True, exist_ok=True)
LOG = DATA_ROOT / "app.log"
logging.basicConfig(
    handlers=[RotatingFileHandler(LOG, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")],
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
)


def port_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, PORT))
            return True
        except OSError:
            return False


def open_when_ready() -> None:
    url = f"http://{HOST}:{PORT}/api/health"
    for _ in range(60):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(f"http://{HOST}:{PORT}")
                    return
        except Exception:
            time.sleep(0.5)
    print("[AVISO] El navegador no se abrió automáticamente.")
    print(f"Abra manualmente http://{HOST}:{PORT}")


def main() -> int:
    if not port_free():
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/openapi.json", timeout=2) as response:
                existing = json.load(response)
            if existing.get("info", {}).get("title") == APP_NAME:
                if os.environ.get("FISCALOPS_NO_BROWSER") != "1":
                    webbrowser.open(f"http://{HOST}:{PORT}")
                print(f"FiscalOps ya está abierto en http://{HOST}:{PORT}")
                return 0
        except (OSError, ValueError):
            pass
        print(f"[ERROR] El puerto {PORT} ya está ocupado.")
        print(f"Si la aplicación ya está abierta, use http://{HOST}:{PORT}")
        return 2
    print("=" * 62)
    print(f" {APP_NAME} v{VERSION} {EDITION}")
    print(f" Dirección: http://{HOST}:{PORT}")
    print(" No cierre esta ventana mientras utiliza la aplicación.")
    print(" Para detener el servidor presione Ctrl+C.")
    print("=" * 62)
    if os.environ.get("FISCALOPS_NO_BROWSER") != "1":
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        uvicorn.run("app:app", host=HOST, port=PORT, log_level="info", access_log=True)
        return 0
    except KeyboardInterrupt:
        print("\nServidor detenido por el usuario.")
        return 0
    except Exception as exc:
        logging.exception("No fue posible iniciar el servidor")
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        print(f"Revise el archivo: {LOG}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
