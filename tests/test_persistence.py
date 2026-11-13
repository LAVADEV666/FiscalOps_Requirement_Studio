import json
from persistence import atomic_json, load_json_recover, session_summary, atomic_replace

def test_atomic_backup_recovery(tmp_path):
    path=tmp_path/'workspace.json'; atomic_json(path,{'version':1}); atomic_json(path,{'version':2})
    path.write_text('{corrupt',encoding='utf-8')
    assert load_json_recover(path)=={'version':1}

def test_session_summary(tmp_path):
    d=tmp_path/('a'*32); d.mkdir(); atomic_json(d/'workspace.json',{'source_file':'req.pdf','points':[{}],'metadata_validation':{'fields':{'rfc':{'value':'ABC010101XX0'}}}})
    result=session_summary(d); assert result['recoverable'] and result['points']==1


def test_windows_sharing_lock_retries_without_losing_original(tmp_path,monkeypatch):
    import persistence
    source=tmp_path/'incoming.tmp';target=tmp_path/'original.docx'
    source.write_bytes(b'Nuevo documento');target.write_bytes(b'Original')
    replace=persistence.os.replace
    attempts=[]
    def locked_then_replace(source,target):
        attempts.append(1)
        if len(attempts)<3:
            assert target.read_bytes()==b'Original'
            error=PermissionError('Archivo temporalmente en uso');error.winerror=32
            raise error
        replace(source,target)
    monkeypatch.setattr(persistence.os,'replace',locked_then_replace)
    monkeypatch.setattr(persistence.time,'sleep',lambda seconds:None)
    atomic_replace(source,target)
    assert target.read_bytes()==b'Nuevo documento' and not source.exists()


def test_permanent_replace_error_preserves_original_and_pending_bytes(tmp_path,monkeypatch):
    import persistence
    import pytest
    source=tmp_path/'incoming.tmp';target=tmp_path/'original.docx'
    source.write_bytes(b'Pendiente');target.write_bytes(b'Original')
    def locked(source,target):
        error=PermissionError('Archivo bloqueado');error.winerror=5
        raise error
    monkeypatch.setattr(persistence.os,'replace',locked)
    monkeypatch.setattr(persistence.time,'sleep',lambda seconds:None)
    with pytest.raises(PermissionError):atomic_replace(source,target)
    assert target.read_bytes()==b'Original' and source.read_bytes()==b'Pendiente'
