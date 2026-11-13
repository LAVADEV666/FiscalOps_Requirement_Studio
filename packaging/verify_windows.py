"""Exercise a built release using its own runtime and synthetic data only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    scratch = args.scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ["FISCALOPS_DATA_DIR"] = str(scratch / "data")
    os.environ["FISCALOPS_NO_BROWSER"] = "1"
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(scratch / "model-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"

    # The OCR must use the bundled models, even without external network access.
    real_connect = socket.socket.connect

    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise OSError("External network disabled during release verification")
        return real_connect(sock, address)

    socket.socket.connect = local_connect
    import config
    assert Path(config.__file__).resolve().parent == root, config.__file__
    assert config.DATA_ROOT == scratch / "data"
    if not args.skip_ocr:
        from PIL import Image, ImageDraw, ImageFont
        from paddle_ocr_engine.modern import ModernOCR, ModernLayoutAnalyzer
        image = Image.new("RGB", (1300, 260), "white")
        font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "arial.ttf"), 42)
        ImageDraw.Draw(image).text((45, 80), "1. Proporcione documentos fiscales.", fill="black", font=font)
        page = scratch / "ocr-sintetico.png"
        image.save(page)
        import numpy as np
        models = root / "models" / "paddleocr"
        ocr = ModernOCR(models)
        lines = ocr.ocr(np.asarray(image))[0]
        text = " ".join(line[1][0] for line in lines)
        assert "documentos" in text.lower(), text
        print("[OK] OCR sin red externa: " + text, flush=True)
        layout = ModernLayoutAnalyzer(models).analyze(page)
        assert layout["size"] == [1300, 260]
        print("[OK] Modelo de layout local cargado.", flush=True)

    # Do not touch a server that was already running.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", config.PORT))
    log_path = scratch / "server.log"
    with log_path.open("wb") as log:
        server = subprocess.Popen([str(root / "FiscalOps.exe"), "--no-browser"],
                                  cwd=scratch, stdout=log, stderr=log)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base = f"http://127.0.0.1:{config.PORT}"
            for _ in range(120):
                if server.poll() is not None:
                    raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace"))
                try:
                    with opener.open(base + "/openapi.json", timeout=2) as response:
                        info = json.load(response)
                    if info["info"]["title"] == config.APP_NAME:
                        break
                except (OSError, ValueError):
                    time.sleep(.5)
            else:
                raise RuntimeError("El servidor no respondió a tiempo")
            with opener.open(base + "/api/health", timeout=15) as response:
                assert json.load(response)["version"] == config.VERSION
            with opener.open(base, timeout=5) as response:
                assert b"<html" in response.read().lower()
            subprocess.run([str(root / "FiscalOps.exe"), "--no-browser"], cwd=scratch, check=True, timeout=15)
            print("[OK] EXE: arranque, interfaz, health y segunda apertura.", flush=True)
        finally:
            if server.poll() is None:
                request = urllib.request.Request(base + "/api/shutdown", data=b"{}", method="POST")
                try:
                    opener.open(request, timeout=5).close()
                    server.wait(timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], check=False)
                    server.wait(timeout=10)
    print("[OK] Comprobación funcional completa.", flush=True)


if __name__ == "__main__":
    main()
