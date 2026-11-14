"""Safe, local-only Ollama provider used by the hybrid pipeline."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable
from urllib.parse import urlparse


SUPPORTED_MODELS = ("qwen2.5:3b", "qwen2.5:1.5b", "llama3.2:3b")


@dataclass(frozen=True)
class OllamaConfig:
    enabled: bool = False
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"
    timeout_seconds: float = 120.0
    retries: int = 1
    block_size: int = 12000
    overlap: int = 800

    @classmethod
    def from_env(cls) -> "OllamaConfig":
        enabled = os.environ.get("FISCALOPS_OLLAMA_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
        config = cls(
            enabled=enabled,
            base_url=os.environ.get("FISCALOPS_OLLAMA_URL", cls.base_url).rstrip("/"),
            model=os.environ.get("FISCALOPS_OLLAMA_MODEL", cls.model),
            timeout_seconds=float(os.environ.get("FISCALOPS_OLLAMA_TIMEOUT", cls.timeout_seconds)),
            retries=max(0, int(os.environ.get("FISCALOPS_OLLAMA_RETRIES", cls.retries))),
            block_size=max(1000, int(os.environ.get("FISCALOPS_OLLAMA_BLOCK_SIZE", cls.block_size))),
            overlap=max(0, int(os.environ.get("FISCALOPS_OLLAMA_OVERLAP", cls.overlap))),
        )
        config.validate()
        return config

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Ollama solo puede configurarse en loopback local.")
        if self.overlap >= self.block_size:
            raise ValueError("El solapamiento Ollama debe ser menor que el tamaño de bloque.")


class OllamaClient:
    def __init__(self, config: OllamaConfig | None = None, opener: Callable[..., Any] | None = None) -> None:
        self.config = config or OllamaConfig.from_env()
        self._open = opener or urllib.request.urlopen

    def _request(self, path: str, payload: dict[str, Any] | None = None, cancel: Event | None = None) -> dict[str, Any]:
        if cancel and cancel.is_set():
            raise RuntimeError("Operación Ollama cancelada.")
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.base_url}{path}", data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST" if body is not None else "GET",
        )
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            if cancel and cancel.is_set():
                raise RuntimeError("Operación Ollama cancelada.")
            started = time.perf_counter()
            try:
                with self._open(request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                result = json.loads(raw)
                result["_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                result["_attempt"] = attempt + 1
                return result
            except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(min(0.25 * (attempt + 1), 1.0))
        raise RuntimeError(f"Ollama local no está disponible: {last_error}") from last_error

    def health(self) -> dict[str, Any]:
        try:
            # / returns plain text in Ollama; /api/tags is JSON and proves the
            # server is reachable without loading or executing a model.
            self._request("/api/tags")
            return {"available": True, "local_only": True, "endpoint": self.config.base_url}
        except RuntimeError as exc:
            return {"available": False, "local_only": True, "endpoint": self.config.base_url, "error": str(exc)}

    def list_models(self) -> list[str]:
        payload = self._request("/api/tags")
        return [str(item.get("name", "")) for item in payload.get("models", []) if item.get("name")]

    def status(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {
                "available": False,
                "enabled": False,
                "local_only": True,
                "endpoint": self.config.base_url,
                "model": self.config.model,
                "supported_models": list(SUPPORTED_MODELS),
                "installed": [],
                "model_available": False,
                "timeout_seconds": self.config.timeout_seconds,
                "retries": self.config.retries,
                "reason": "Desactivado por configuración.",
            }
        health = self.health()
        installed: list[str] = []
        if health.get("available"):
            try:
                installed = self.list_models()
            except RuntimeError as exc:
                health.update(available=False, error=str(exc))
        return {
            **health,
            "enabled": self.config.enabled,
            "model": self.config.model,
            "supported_models": list(SUPPORTED_MODELS),
            "installed": installed,
            "model_available": self.config.model in installed,
            "timeout_seconds": self.config.timeout_seconds,
            "retries": self.config.retries,
        }

    def generate_json(self, prompt: str, *, system: str = "", cancel: Event | None = None) -> dict[str, Any]:
        status = self.status()
        if not status.get("available"):
            raise RuntimeError(status.get("error", "Ollama no está disponible."))
        if not status.get("model_available"):
            raise RuntimeError(f"El modelo local {self.config.model} no está instalado.")
        payload = self._request("/api/generate", {
            "model": self.config.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": 0,
            "options": {"temperature": 0, "num_ctx": 4096},
        }, cancel=cancel)
        try:
            parsed = json.loads(str(payload.get("response", "{}")))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama devolvió JSON inválido.") from exc
        return {"result": parsed, "latency_ms": payload.get("_latency_ms"), "model": self.config.model}


def chunk_text(text: str, block_size: int, overlap: int) -> list[str]:
    value = str(text or "")
    if not value:
        return []
    step = max(1, block_size - overlap)
    return [value[start:start + block_size] for start in range(0, len(value), step)]
