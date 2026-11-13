import io
import json
import os
import struct
from unittest.mock import patch

import pytest

import build_windows
import desktop_entry
import launcher


def test_release_allowlist_never_selects_operational_folders(tmp_path):
    assert {"app", "desktop_entry", "launcher", "config"} <= set(build_windows.APP_MODULES)
    assert all("/" not in name and "\\" not in name for name in build_windows.APP_MODULES)
    source = tmp_path / "source"
    (source / "__pycache__").mkdir(parents=True)
    (source / "__pycache__" / "private.pyc").write_bytes(b"cache")
    (source / "module.py").write_text("pass")
    (source / "startup.log").write_text("private")
    destination = tmp_path / "release"
    build_windows.copy_tree(source, destination)
    assert [p.name for p in destination.rglob("*") if p.is_file()] == ["module.py"]


def test_portable_marker_selects_adjacent_data_without_overriding_user(tmp_path, monkeypatch):
    # Register the original environment even when the variable was absent.
    monkeypatch.setenv("FISCALOPS_DATA_DIR", "")
    monkeypatch.delenv("FISCALOPS_DATA_DIR", raising=False)
    desktop_entry.configure_paths(tmp_path)
    assert "FISCALOPS_DATA_DIR" not in os.environ
    (tmp_path / "portable.flag").touch()
    desktop_entry.configure_paths(tmp_path)
    assert os.environ["FISCALOPS_DATA_DIR"] == str(tmp_path / "datos_usuario")
    monkeypatch.setenv("FISCALOPS_DATA_DIR", str(tmp_path / "custom"))
    desktop_entry.configure_paths(tmp_path)
    assert os.environ["FISCALOPS_DATA_DIR"] == str(tmp_path / "custom")


def test_builder_refuses_existing_release_before_copying(tmp_path):
    (tmp_path / build_windows.RELEASE_NAME).mkdir()
    with pytest.raises(ValueError, match="Ya existe"):
        build_windows.build(tmp_path)


def test_second_launch_reuses_fiscalops_and_leaves_other_services_alone(monkeypatch):
    monkeypatch.setenv("FISCALOPS_NO_BROWSER", "1")
    with patch.object(launcher, "port_free", return_value=False):
        for title, expected in (("FiscalOps Requirement Studio", 0), ("Otra aplicación", 2)):
            response = io.BytesIO(json.dumps({"info": {"title": title}}).encode())
            with patch.object(launcher.urllib.request, "urlopen", return_value=response):
                assert launcher.main() == expected


def test_native_runtime_is_bundled_locally_and_rejects_other_architectures(tmp_path,monkeypatch):
    monkeypatch.setattr(build_windows,"ROOT",tmp_path/'source')
    system=tmp_path/'system';system.mkdir()
    library=bytearray(128);library[:2]=b'MZ';struct.pack_into('<I',library,0x3c,64);library[64:70]=b'PE\0\0\x64\x86'
    for name in build_windows.NATIVE_RUNTIME:(system/name).write_bytes(library)
    destination=tmp_path/'app'/'runtime'
    build_windows.bundle_native_runtime(destination,system)
    assert all((destination/name).read_bytes()==library for name in build_windows.NATIVE_RUNTIME)
    metadata=json.loads((destination/'NATIVE_RUNTIME.json').read_text())
    assert {item['name'] for item in metadata['files']}==set(build_windows.NATIVE_RUNTIME)
    library[68:70]=b'\x4c\x01'
    (system/'vcomp140.dll').write_bytes(library)
    with pytest.raises(ValueError,match='x64'):build_windows.bundle_native_runtime(destination,system)


def test_portable_manifest_and_zip_have_matching_content(tmp_path):
    folder=tmp_path/'FiscalOps';(folder/'static').mkdir(parents=True)
    (folder/'app.py').write_text('pass')
    (folder/'static'/'MANIFEST.json').write_text('{}')
    build_windows.write_manifest(folder)
    manifest=json.loads((folder/'MANIFEST.json').read_text())
    assert {item['path'] for item in manifest['files']}=={'app.py','static/MANIFEST.json'}
    archive=tmp_path/'FiscalOps.zip';build_windows.write_archive(folder,archive)
    from zipfile import ZipFile
    with ZipFile(archive) as package:
        assert package.testzip() is None
        assert len(package.namelist())==3
    with pytest.raises(ValueError,match='fuera'):build_windows.write_archive(folder,folder/'recursive.zip')
