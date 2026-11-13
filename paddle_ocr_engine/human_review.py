from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CorrectionsStore:
    """Registro append-only de decisiones humanas y diccionario fiscal local."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "corrections.jsonl"
        self.dictionary_path = self.root / "fiscal_dictionary.json"
        self._lock = threading.Lock()

    def record(self, item: dict[str, Any]) -> dict[str, Any]:
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **item}
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            original = str(entry.get("original_text", "")).strip()
            corrected = str(entry.get("corrected_text", "")).strip()
            if original and corrected and original != corrected:
                try:
                    dictionary = json.loads(self.dictionary_path.read_text(encoding="utf-8"))
                except Exception:
                    dictionary = {"schema_version": "1.0.0", "pairs": {}}
                key = f"{original}\u241f{corrected}"
                row = dictionary.setdefault("pairs", {}).setdefault(key, {"original": original, "corrected": corrected, "count": 0})
                row["count"] = int(row.get("count", 0)) + 1
                temp = self.dictionary_path.with_suffix(".tmp")
                temp.write_text(json.dumps(dictionary, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temp, self.dictionary_path)
        return entry
