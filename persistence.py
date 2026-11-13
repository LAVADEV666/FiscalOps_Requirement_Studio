from __future__ import annotations
import json, os, shutil, tempfile, time
from datetime import datetime, timezone
from threading import RLock
from pathlib import Path
from typing import Any

class PersistenceError(RuntimeError): pass


class RevisionConflict(PersistenceError):
    def __init__(self, revision: int):
        super().__init__("Hay una versión más reciente del expediente. Conserva tu borrador antes de recargar.")
        self.revision = revision


_workspace_locks = [RLock() for _ in range(64)]


def workspace_lock(folder: Path):
    return _workspace_locks[hash(folder.resolve()) % len(_workspace_locks)]


def atomic_replace(source: Path, target: Path) -> None:
    """Keep replacement atomic while tolerating short Windows sharing locks."""
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if attempt == 4 or getattr(error, 'winerror', None) not in {5, 32, 33}:
                raise
            time.sleep(.025 * 2**attempt)


def commit_workspace(folder: Path, data: dict, expected: int | None = None,
                     *, restore: bool = False) -> int:
    path = folder / "workspace.json"
    with workspace_lock(folder):
        current = load_json_recover(path)
        revision = current.get("workspace_revision", 0)
        if (data.get("workspace_revision", 0) if expected is None else expected) != revision:
            raise RevisionConflict(revision)
        if restore:
            data["audit_log"] = [*current.get("audit_log", []), {
                "timestamp": utc_now(), "action": "WORKSPACE_REVISION_RESTORED",
                "after": str(data.get("workspace_revision", 0)),
            }]
        history = folder / "history"
        atomic_json(history / f"{revision:012d}.json", current, backup=False)
        data["workspace_revision"] = revision + 1
        data["workspace_saved_at"] = utc_now()
        atomic_json(path, data)
        for old in sorted(history.glob("[0-9]*.json"), reverse=True)[20:]:
            try:
                old.unlink()
            except OSError:
                pass
        return revision + 1


def workspace_history(folder: Path) -> list[dict]:
    with workspace_lock(folder):
        current = load_json_recover(folder / "workspace.json")
        entries = []
        for path in sorted((folder / "history").glob("[0-9]*.json"), reverse=True):
            if not path.stem.isdecimal() or int(path.stem) >= current.get("workspace_revision", 0):
                continue
            item = load_json_recover(path)
            entries.append({"revision": int(path.stem), "saved_at": item.get("workspace_saved_at"),
                            "action": (item.get("audit_log") or [{}])[-1].get("action")})
        return entries


def restore_workspace(folder: Path, revision: int, expected: int) -> dict:
    with workspace_lock(folder):
        path = folder / "history" / f"{revision:012d}.json"
        current = load_json_recover(folder / "workspace.json")
        if not path.is_file() or not 0 <= revision < current.get("workspace_revision", 0):
            raise FileNotFoundError("Versión no encontrada.")
        data = load_json_recover(path)
        commit_workspace(folder, data, expected, restore=True)
        return data

def utc_now() -> str: return datetime.now(timezone.utc).isoformat()

def atomic_json(path: Path, data: Any, backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        fd, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
        tmp_path = Path(name)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        json.loads(tmp_path.read_text(encoding='utf-8'))
        if backup and path.exists(): shutil.copy2(path, path.with_suffix(path.suffix+'.bak'))
        atomic_replace(tmp_path, path)
    except Exception as exc:
        if tmp_path and tmp_path.exists(): tmp_path.unlink(missing_ok=True)
        raise PersistenceError(f'No fue posible guardar {path.name}: {exc}') from exc

def load_json_recover(path: Path) -> dict[str, Any]:
    errors=[]
    for candidate in (path, path.with_suffix(path.suffix+'.bak')):
        if not candidate.exists(): continue
        try:
            value=json.loads(candidate.read_text(encoding='utf-8'))
            if not isinstance(value,dict): raise ValueError('La raíz no es un objeto JSON.')
            if candidate != path: atomic_json(path,value,backup=False)
            return value
        except Exception as exc: errors.append(f'{candidate.name}: {exc}')
    raise PersistenceError('Workspace no recuperable. '+'; '.join(errors))

def session_activity_stamp(folder: Path) -> float:
    files = [folder/'workspace.json', folder/'library.json', folder/'wordcraft'/'document.docx']
    stamps = [path.stat().st_mtime for path in files if path.is_file()]
    return max(stamps) if stamps else folder.stat().st_mtime


def session_summary(folder: Path) -> dict[str, Any]:
    ws=folder/'workspace.json'
    try:
        data=load_json_recover(ws)
        fields=data.get('metadata_validation',{}).get('fields',{})
        def val(k): return fields.get(k,{}).get('value','')
        return {'job_id':folder.name,'source_file':data.get('source_file',''),'rfc':val('rfc'),
                'taxpayer_name':val('taxpayer_name'),'points':len(data.get('points',[])),
                  'updated_at':datetime.fromtimestamp(session_activity_stamp(folder),timezone.utc).isoformat(),'recoverable':True,
                  'organization':load_json_recover(folder/'library.json') if (folder/'library.json').exists() else {}}
    except Exception as exc:
        return {'job_id':folder.name,'recoverable':False,'error':str(exc)}
