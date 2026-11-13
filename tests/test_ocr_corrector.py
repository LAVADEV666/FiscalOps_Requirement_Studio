import io
import json

import pytest

from paddle_ocr_engine.corrector import OllamaCorrector, REQUIRED_ENV


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def fake_open(request, timeout=0):
    if request.full_url.endswith("/api/tags"):
        body = {"models": [{"name": "gemma3:4b"}]}
    else:
        body = {"response": json.dumps({"corrected_text": "1. Proporcione información", "changes": ["informaci6n → información"]})}
    return Response(json.dumps(body).encode())


def test_corrector_rejects_non_loopback():
    with pytest.raises(ValueError):
        OllamaCorrector(base_url="https://example.com")


def test_corrector_returns_reviewable_suggestion(monkeypatch):
    for key, value in REQUIRED_ENV.items(): monkeypatch.setenv(key, value)
    result = OllamaCorrector(opener=fake_open).suggest("1. Proporcione informaci6n", "1")
    assert result["suggested_text"].endswith("información")
    assert result["requires_human_review"] is True and result["applied"] is False
    assert len(result["source_text_sha256"]) == 64


def test_corrector_rejects_changed_protected_numbers(monkeypatch):
    for key, value in REQUIRED_ENV.items(): monkeypatch.setenv(key, value)
    def unsafe_open(request, timeout=0):
        body = {"models": [{"name": "gemma3:4b"}]} if request.full_url.endswith("/api/tags") else {"response": json.dumps({"corrected_text": "2. Ejercicio 2024", "changes": []})}
        return Response(json.dumps(body).encode())
    with pytest.raises(RuntimeError, match="protegidos"):
        OllamaCorrector(opener=unsafe_open).suggest("1. Ejercicio 2025", "1")

