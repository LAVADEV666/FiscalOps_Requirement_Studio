from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json

import pytest

from persistence import RevisionConflict, atomic_json, commit_workspace, load_json_recover, restore_workspace, workspace_history
from workspace_backup import rebase_evidence, restore_archive, write_backup


def test_concurrent_saves_and_restore_keep_both_committed_revisions(tmp_path):
    path = tmp_path / "workspace.json"
    atomic_json(path, {"title": "Original"})

    def save(title):
        try:
            return commit_workspace(tmp_path, {"title": title, "workspace_revision": 0})
        except RevisionConflict as conflict:
            return conflict.revision, title

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ("Pestaña A", "Pestaña B")))
    assert results.count(1) == 1
    loser = next(value for value in results if isinstance(value, tuple))
    assert loser[0] == 1
    winner = load_json_recover(path)["title"]
    assert winner != loser[1]
    with pytest.raises(RevisionConflict):
        restore_workspace(tmp_path, 0, expected=0)
    restored = restore_workspace(tmp_path, 0, expected=1)
    assert restored["title"] == "Original"
    assert restored["workspace_revision"] == 2
    assert [item["revision"] for item in workspace_history(tmp_path)] == [1, 0]
    assert load_json_recover(tmp_path / "history" / "000000000001.json")["title"] == winner


def test_restore_relocates_evidence_and_rejects_corrupt_zip(tmp_path):
    original = tmp_path / "original"
    evidence = original / "evidence_source" / "anexo.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("evidencia original", encoding="utf-8")
    data = {"evidence_index": {"records": [{"relative_path": "anexo.txt", "source_path": str(evidence)}]}}
    atomic_json(original / "workspace.json", data)
    commit_workspace(original, data)
    (original / "assets").mkdir()
    (original / "assets" / "visual.png").write_bytes(b"recurso de prueba")
    archive = tmp_path / "backup.zip"
    write_backup(original, archive, {"schema": "fiscalops.workspace.v1"})

    def prepare(stage, destination, manifest):
        assert manifest["schema"] == "fiscalops.workspace.v1"
        rebase_evidence(stage, destination)

    restored = tmp_path / "new-installation" / "restored"
    restore_archive(archive, restored, prepare)
    for path in (restored / "workspace.json", restored / "history" / "000000000000.json"):
        record = load_json_recover(path)["evidence_index"]["records"][0]
        assert Path(record["source_path"]) == restored / "evidence_source" / "anexo.txt"
        assert Path(record["source_path"]).read_text(encoding="utf-8") == "evidencia original"
    assert (restored / "assets" / "visual.png").is_file()

    altered = tmp_path / "altered.zip"
    with ZipFile(archive) as source, ZipFile(altered, "w") as destination:
        for entry in source.namelist():
            content = source.read(entry)
            if entry == "assets/visual.png":
                content = b"X" * len(content)
            destination.writestr(entry, content)
    refused = tmp_path / "refused"
    with pytest.raises(ValueError, match="no coincide"):
        restore_archive(altered, refused, prepare)
    assert not refused.exists()


def test_restore_rejects_escaping_archive_even_with_valid_digest(tmp_path):
    file = tmp_path / "escape.zip"
    name = "../escape.txt"
    content = b"contenido"
    manifest = {"files": [{"file": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}]}
    with ZipFile(file, "w") as archive:
        archive.writestr(name, content)
        archive.writestr("MANIFEST.json", json.dumps(manifest))
    with pytest.raises(ValueError, match="ruta inválida"):
        restore_archive(file, tmp_path / "restored", lambda *_: None)
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "restored").exists()
