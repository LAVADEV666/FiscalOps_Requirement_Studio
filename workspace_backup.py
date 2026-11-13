from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

from persistence import atomic_json, load_json_recover

MAX_BACKUP = 2 * 1024**3
MAX_ENTRIES = 20000


def safe_archive_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or path.as_posix() != name
            or any(part in {".", ".."} or part.endswith((".", " "))
                   or re.search(r'[<>:"\\|?*\x00-\x1f]', part)
                   or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])", part.split(".")[0])
                   for part in path.parts)):
        raise ValueError("El respaldo contiene una ruta inválida.")
    return path


def transfer(source, target) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
        target.write(chunk)
    return size, digest.hexdigest()


def write_backup(folder: Path, output: Path, metadata: dict) -> list[dict]:
    root = folder.resolve()
    files = []
    total = 0
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            if path.suffix == ".tmp":
                continue
            name = path.relative_to(folder).as_posix()
            safe_archive_name(name)
            if name == "MANIFEST.json" or len(files) >= MAX_ENTRIES or total + path.stat().st_size > MAX_BACKUP:
                raise ValueError("El expediente excede el límite del respaldo o contiene archivos reservados.")
            with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                size, digest = transfer(source, target)
            total += size
            files.append({"file": name, "size": size, "sha256": digest})
        archive.writestr("MANIFEST.json", json.dumps({**metadata, "files": files}, ensure_ascii=False))
    return files


def restore_archive(source: Path, destination: Path, prepare) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("El destino ya existe.")
    with ZipFile(source) as archive, tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        staging = Path(temp) / "restored"
        staging.mkdir()
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES + 1 or sum(item.file_size for item in entries) > MAX_BACKUP + 8 * 1024**2:
            raise ValueError("El respaldo excede el tamaño permitido.")
        names = [item.filename for item in entries]
        if len(set(name.casefold() for name in names)) != len(names) or "MANIFEST.json" not in names:
            raise ValueError("El respaldo contiene archivos repetidos o carece de manifiesto.")
        if archive.getinfo("MANIFEST.json").file_size > 8 * 1024**2:
            raise ValueError("Manifiesto demasiado grande.")
        manifest = json.loads(archive.read("MANIFEST.json"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
            raise ValueError("Manifiesto inválido.")
        records = manifest["files"]
        if not all(isinstance(item, dict) and isinstance(item.get("file"), str) for item in records):
            raise ValueError("Inventario del respaldo inválido.")
        listed = {item["file"]: item for item in records}
        if len(listed) != len(records) or set(names) != set(listed) | {"MANIFEST.json"} or "MANIFEST.json" in listed:
            raise ValueError("El contenido del respaldo no coincide con el manifiesto.")
        for name, record in listed.items():
            relative = safe_archive_name(name)
            if archive.getinfo(name).file_size != record.get("size"):
                raise ValueError(f"Tamaño inválido: {name}")
            path = staging.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as member, path.open("xb") as target:
                size, digest = transfer(member, target)
            if size != record.get("size") or digest != record.get("sha256"):
                raise ValueError(f"El archivo no coincide con el respaldo: {name}")
        prepare(staging, destination, manifest)
        staging.rename(destination)
        return manifest


def rebase_evidence(staging: Path, destination: Path, workspace: Path | None = None) -> None:
    workspace = workspace or staging / "workspace.json"
    def relocate(index):
        index["source_folder"] = str(destination / "evidence_source")
        for record in index.get("records", []):
            relative = safe_archive_name(str(record.get("relative_path", "")).replace("\\", "/"))
            record["source_path"] = str(destination / "evidence_source" / relative)

    if workspace.is_file():
        data = load_json_recover(workspace)
        if isinstance(data.get("evidence_index"), dict):
            relocate(data["evidence_index"])
            atomic_json(workspace, data, backup=False)
    # A restored historical revision must also refer to the restored files.
    for path in [*(staging / "history").glob("*.json"), staging / "workspace.json.bak"]:
        if path.is_file():
            data = load_json_recover(path)
            if isinstance(data.get("evidence_index"), dict):
                relocate(data["evidence_index"])
                atomic_json(path, data, backup=False)
    index = staging / "evidence_index.json"
    if index.is_file():
        data = load_json_recover(index)
        relocate(data)
        atomic_json(index, data, backup=False)
