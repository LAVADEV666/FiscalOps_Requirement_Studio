from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Callable


REQUIRED_ENV = {
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_CONTEXT_LENGTH": "2048",
    "OLLAMA_FLASH_ATTENTION": "0",
}


class OllamaCorrector:
    """Corrector post-OCR local. Solo genera sugerencias revisables."""

    def __init__(
        self,
        model: str = "gemma3:4b",
        base_url: str = "http://127.0.0.1:11434",
        timeout: int = 120,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        if base_url.rstrip("/") not in {"http://127.0.0.1:11434", "http://localhost:11434"}:
            raise ValueError("Ollama debe ejecutarse exclusivamente en loopback local.")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    @staticmethod
    def configure_environment() -> None:
        for key, value in REQUIRED_ENV.items():
            os.environ.setdefault(key, value)

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body,
            headers={"Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        try:
            with self._open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama local no está disponible: {exc}") from exc

    def status(self) -> dict[str, Any]:
        try:
            payload = self._request("/api/tags")
            installed = [str(item.get("name", "")) for item in payload.get("models", [])]
        except RuntimeError as exc:
            return {"available": False, "model": self.model, "installed": [], "local_only": True, "error": str(exc)}
        return {
            "available": self.model in installed,
            "model": self.model,
            "installed": installed,
            "local_only": True,
            "environment": {key: os.environ.get(key, "") for key in REQUIRED_ENV},
            "environment_compliant": all(os.environ.get(k) == v for k, v in REQUIRED_ENV.items()),
        }

    def suggest(self, text: str, numeral: str = "") -> dict[str, Any]:
        source = str(text).strip()
        if not source:
            raise ValueError("No hay texto OCR que corregir.")
        status = self.status()
        if not status.get("available"):
            raise RuntimeError(f"El modelo local requerido {self.model} no está instalado.")
        protected = re.findall(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b|\b\d[\d.,/%-]*\b", source.upper())
        prompt = (
            "Eres un corrector conservador de OCR jurídico-fiscal mexicano. "
            "Corrige solo errores evidentes de reconocimiento (caracteres confundidos, espacios o cortes). "
            "No resumas, no reformules, no agregues ni elimines obligaciones, cifras, RFC, fechas o fundamentos. "
            "Conserva exactamente el prefijo numeral y todos estos tokens protegidos: "
            f"{protected}. "
            "Devuelve JSON estricto con corrected_text y changes (lista breve). "
            f"Numeral asociado: {numeral or 'no identificado'}\nTexto OCR:\n{source}"
        )
        payload = self._request("/api/generate", {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": 0,
            "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 512},
        })
        try:
            result = json.loads(str(payload.get("response", "{}")))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama devolvió una sugerencia no estructurada.") from exc
        corrected = str(result.get("corrected_text", "")).strip()
        if not corrected:
            raise RuntimeError("Ollama no devolvió corrected_text.")
        corrected_protected = re.findall(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b|\b\d[\d.,/%-]*\b", corrected.upper())
        if Counter(protected) != Counter(corrected_protected):
            raise RuntimeError("Sugerencia rechazada: alteró numerales, cifras, fechas o RFC protegidos.")
        similarity = SequenceMatcher(None, source, corrected).ratio()
        length_delta = abs(len(corrected) - len(source)) / max(1, len(source))
        if similarity < 0.78 or length_delta > 0.20:
            raise RuntimeError("Sugerencia rechazada: se aleja demasiado del texto OCR original.")
        return {
            "model": self.model,
            "source_text_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "suggested_text": corrected,
            "changes": [str(x) for x in result.get("changes", [])][:20],
            "validation": {"protected_tokens": protected, "similarity": round(similarity, 4)},
            "requires_human_review": True,
            "applied": False,
        }
