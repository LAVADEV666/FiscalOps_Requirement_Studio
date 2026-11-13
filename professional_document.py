"""Versioned final DOCX artifacts; the canonical OCR workspace remains traceable."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile

from template_store import load_template
from persistence import atomic_replace


def revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def save_document(path: Path, content: bytes, expected: str) -> str:
    # The caller holds the workspace lock through revision checking and replacement.
    load_template(content, allow_export=True)
    if revision(path) != expected:
        raise ValueError("El documento cambió en otra sesión. Descarga tus cambios y vuelve a abrirlo.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        # Preserve WordCraft's package byte for byte, including comments, revisions,
        # references and custom parts that python-docx does not author itself.
        temporary.write_bytes(content)
        atomic_replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return revision(path)
