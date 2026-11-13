"""Local, user-created backup catalog. Reading never removes records."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import uuid

from persistence import atomic_json, load_json_recover, session_summary, workspace_lock
from workspace_backup import write_backup


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class BackupStore:
    def __init__(self, root: Path):
        self.root = root

    def path(self, backup_id):
        if not re.fullmatch(r'[a-f0-9]{32}', backup_id):
            raise ValueError('Identificador de resguardo inválido.')
        path = self.root / (backup_id + '.zip')
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Ruta de resguardo inválida.')
        return path

    def create(self, folder: Path, title=''):
        self.root.mkdir(parents=True, exist_ok=True)
        backup_id = uuid.uuid4().hex
        path = self.path(backup_id)
        with workspace_lock(folder):
            summary = session_summary(folder)
            if not summary['recoverable']:
                raise ValueError('El expediente no se puede respaldar.')
            try:
                write_backup(folder, path, {'schema':'fiscalops.workspace.v1'})
                item = {'id':backup_id, 'job_id':folder.name, 'title':title.strip() or summary.get('taxpayer_name') or summary.get('source_file') or 'Expediente FiscalOps',
                        'rfc':summary.get('rfc',''), 'created_at':datetime.now(timezone.utc).isoformat(),
                        'bytes':path.stat().st_size, 'sha256':file_digest(path), 'archived':False}
                atomic_json(path.with_suffix('.json'), item)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        return item

    def list(self):
        items = []
        for file in self.root.glob('*.json'):
            if not re.fullmatch(r'[a-f0-9]{32}', file.stem):
                continue
            item = load_json_recover(file)
            item.update(id=file.stem, available=self.path(file.stem).is_file())
            items.append(item)
        return sorted(items, key=lambda item:item['created_at'], reverse=True)

    def read(self, backup_id):
        path = self.path(backup_id)
        item = load_json_recover(path.with_suffix('.json'))
        if file_digest(path) != item['sha256']:
            raise ValueError('El resguardo no supera la verificación de integridad.')
        return path

    def organize(self, backup_id, title, archived):
        path = self.path(backup_id).with_suffix('.json')
        with workspace_lock(path):
            item = load_json_recover(path)
            item.update(title=title.strip() or item['title'], archived=archived)
            atomic_json(path, item)
        return item
