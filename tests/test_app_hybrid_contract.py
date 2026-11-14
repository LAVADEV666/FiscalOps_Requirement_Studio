from __future__ import annotations

import json
from pathlib import Path


def test_legacy_process_delegates_to_hybrid_pipeline(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app as server

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(server, "WORK", work)
    job_id = "a" * 32
    calls = []

    class FakePipeline:
        def run(self, task_id, input_pdf, **kwargs):
            calls.append((task_id, Path(input_pdf), kwargs))
            folder = work / job_id
            folder.mkdir()
            (folder / "workspace.json").write_text(json.dumps({"pages": 1}), encoding="utf-8")
            return {"session_id": job_id, "job_id": job_id}

    monkeypatch.setattr(server, "pipeline", FakePipeline())
    with TestClient(server.app) as client:
        response = client.post(
            "/api/process",
            files={"file": ("synthetic.pdf", b"%PDF-1.7\nsynthetic", "application/pdf")},
        )
    assert response.status_code == 200
    assert response.json()["job_id"] == job_id
    assert calls and calls[0][2]["recover_ocr"] is True
    assert not list(work.glob("fiscalops-upload-*"))
