from io import BytesIO
import os
import time

from PIL import Image
import pytest

from backup_store import BackupStore
from document_model import ensure_document
from enterprise_store import EnterpriseStore
from maintenance import clean_sessions, retired_sessions, restore_retired, purge_retired
from persistence import atomic_json, load_json_recover, session_activity_stamp


def sample_workspace(folder):
    folder.mkdir(parents=True)
    data = {'workspace_revision':0, 'source_file':'Requerimiento.pdf', 'points':[{'number':1,'text':'Texto del requerimiento completo.'}],
            'assets':[], 'metadata_validation':{'fields':{'rfc':{'value':'ABC010101AB1'},'taxpayer_name':{'value':'Empresa A'}}}}
    ensure_document(data)
    atomic_json(folder/'workspace.json', data)
    (folder/'source.pdf').write_bytes(b'%PDF-1.7\nTest')
    return data


def test_company_cover_validation_and_appearance_preserve_company(tmp_path):
    store = EnterpriseStore(tmp_path)
    store.create_company('ABC010101AB1','Empresa A')
    store.create_case('ABC010101AB1','caso','Caso A')
    output = BytesIO()
    Image.new('RGBA',(20,20),'#123456').save(output,format='PNG')
    profile = store.set_cover('ABC010101AB1',output.getvalue())
    assert profile['name'] == 'Empresa A'
    with Image.open(store.company_dir('ABC010101AB1')/'cover.png') as image:
        assert image.size == (1200,480)
    store.appearance('ABC010101AB1','🏦','#123456',False)
    store.create_company('ABC010101AB1','Empresa actualizada')
    profile = store.list_companies()[0]
    assert profile['case_count'] == 1 and profile['cover_version'] and profile['emoji'] == '🏦'
    assert not profile['use_cover']
    assert store.list_cases('ABC010101AB1')[0]['title'] == 'Caso A'
    with pytest.raises(ValueError):store.set_cover('ABC010101AB1',b'<svg/>')
    with pytest.raises(ValueError):store.appearance('ABC010101AB1','unknown','red')


def test_backup_catalog_integrity_and_restore_input(tmp_path):
    folder = tmp_path/'work'/('a'*32)
    sample_workspace(folder)
    store = BackupStore(tmp_path/'backups')
    item = store.create(folder,'Resguardo A')
    assert store.read(item['id']).is_file()
    store.organize(item['id'],'Resguardo renombrado',True)
    assert store.list()[0]['title'] == 'Resguardo renombrado'
    assert store.list()[0]['archived']
    assert (folder/'workspace.json').exists()
    with pytest.raises(ValueError):store.path('../other')
    store.path(item['id']).write_bytes(b'alterado')
    with pytest.raises(ValueError,match='integridad'):store.read(item['id'])


def test_retirement_is_selective_reversible_and_protects_recent_wordcraft(tmp_path):
    work=tmp_path/'work'
    folder=work/('a'*32)
    sample_workspace(folder)
    (folder/'wordcraft').mkdir()
    (folder/'wordcraft'/'document.docx').write_bytes(b'Conservar este escrito')
    old=time.time()-60*86400
    os.utime(folder/'workspace.json',(old,old))
    assert clean_sessions(work,30,True)['count'] == 0
    os.utime(folder/'wordcraft'/'document.docx',(old,old))
    preview=clean_sessions(work,30,True)
    assert preview['count']==1 and folder.exists()
    selected={item['job_id']:item['modified'] for item in preview['items']}
    atomic_json(folder/'library.json',{'group':'Actualizado'})
    assert clean_sessions(work,30,False,selected)['count']==0
    os.utime(folder/'library.json',(old,old))
    preview=clean_sessions(work,30,True)
    selected={item['job_id']:item['modified'] for item in preview['items']}
    retired=clean_sessions(work,30,False,selected)
    assert not folder.exists() and retired['count']==1
    token=retired['items'][0]['trash_id']
    assert retired_sessions(work)[0]['trash_id']==token
    assert restore_retired(work,token)['job_id']==folder.name
    assert (folder/'wordcraft'/'document.docx').read_bytes()==b'Conservar este escrito'
    assert retired_sessions(work)==[]
    with pytest.raises(ValueError):restore_retired(work,'../../escape')


@pytest.fixture
def api(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import app as server
    work=tmp_path/'work'
    monkeypatch.setattr(server,'WORK',work)
    monkeypatch.setattr(server,'enterprise',EnterpriseStore(tmp_path/'data'))
    monkeypatch.setattr(server,'backups',BackupStore(tmp_path/'data'/'resguardos'))
    folder=work/('a'*32)
    sample_workspace(folder)
    with TestClient(server.app) as client:yield client,folder,server


def test_organization_and_managed_backup_roundtrip(api):
    client,folder,server=api
    original=(folder/'workspace.json').read_bytes()
    url='/api/sessions/'+folder.name+'/organization'
    response=client.put(url,json={'pinned':True,'archived':True,'group':'Revisión 2026'})
    assert response.status_code==200
    assert client.get('/api/sessions').json()['sessions'][0]['organization']['group']=='Revisión 2026'
    assert (folder/'workspace.json').read_bytes()==original
    item=client.post('/api/backups',json={'job_id':folder.name,'title':'Resguardo A'}).json()
    assert client.get('/api/backups').json()['backups'][0]['id']==item['id']
    response=client.get('/api/backups/'+item['id']+'/file')
    assert response.status_code==200
    restored=client.post('/api/workspace/restore',files={'file':('resguardo.zip',response.content)})
    assert restored.status_code==200
    target=server.WORK/restored.json()['job_id']
    assert target!=folder and (folder/'workspace.json').read_bytes()==original
    assert load_json_recover(target/'library.json')['pinned']


def test_cleanup_api_requires_selection_without_written_validator(api):
    client,folder,_=api
    old=time.time()-60*86400
    os.utime(folder/'workspace.json',(old,old))
    preview=client.post('/api/maintenance/cleanup',json={'days':30}).json()
    selected={item['job_id']:item['modified'] for item in preview['items']}
    payload={'days':30,'dry_run':False,'selected':selected}
    assert client.post('/api/maintenance/cleanup',json={'days':30,'dry_run':False}).status_code==400
    assert folder.is_dir()
    response=client.post('/api/maintenance/cleanup',json=payload)
    assert response.status_code==200 and not folder.exists()
    token=response.json()['items'][0]['trash_id']
    assert client.post('/api/maintenance/retired/'+token+'/restore').status_code==200
    assert folder.is_dir()


def test_direct_retire_has_no_age_gate_and_can_be_undone(api):
    client,folder,_=api
    item=client.get('/api/sessions').json()['sessions'][0]
    original=(folder/'workspace.json').read_bytes()
    response=client.post('/api/sessions/'+folder.name+'/retire',json={'expected_updated_at':item['updated_at']})
    assert response.status_code==200 and not folder.exists()
    token=response.json()['trash_id']
    assert client.post('/api/maintenance/retired/'+token+'/restore').status_code==200
    assert (folder/'workspace.json').read_bytes()==original
    assert client.post('/api/sessions/'+folder.name+'/retire',json={'expected_updated_at':'outdated'}).status_code==409
    assert folder.exists()
    all_sessions=client.post('/api/maintenance/cleanup',json={'days':0}).json()
    assert all_sessions['count']==1


def test_company_identity_shares_cover_with_all_views(api):
    client,_,server=api
    rfc='ABC010101AB1'
    assert client.get('/api/companies/'+rfc+'/identity').json()['registered'] is False
    server.enterprise.create_company(rfc,'Empresa A')
    image=BytesIO();Image.new('RGBA',(40,20),'purple').save(image,format='PNG')
    server.enterprise.set_cover(rfc,image.getvalue())
    server.enterprise.appearance(rfc,'🏦','#123456')
    item=client.get('/api/companies/'+rfc+'/identity').json()
    assert item['registered'] and item['cover_version'] and item['name']=='Empresa A'
    assert client.get('/api/companies/'+rfc+'/cover').status_code==200
    server.enterprise.appearance(rfc,'🏦','#123456',False)
    assert client.get('/api/companies/'+rfc+'/identity').json()['cover_version'] is None
    assert client.get('/api/companies/DEF010101AB1/identity').json()['registered'] is False


def test_permanent_cleanup_requires_retired_record_and_matching_confirmation(tmp_path):
    work=tmp_path/'work'
    folder=work/('a'*32)
    other=work/('b'*32)
    sample_workspace(folder);sample_workspace(other)
    old=time.time()-60*86400
    os.utime(folder/'workspace.json',(old,old))
    result=clean_sessions(work,30,False)
    token=result['items'][0]['trash_id']
    with pytest.raises(ValueError):purge_retired(work,token,folder.name,False)
    with pytest.raises(ValueError):purge_retired(work,token,other.name,True)
    assert other.exists() and retired_sessions(work)
    purge_retired(work,token,folder.name,True)
    assert other.exists() and retired_sessions(work)==[]
    with pytest.raises(ValueError):purge_retired(work,'../escape',folder.name,True)


def test_permanent_cleanup_api_keeps_independent_backup(api):
    client,folder,server=api
    backup=client.post('/api/backups',json={'job_id':folder.name}).json()
    old=time.time()-60*86400
    os.utime(folder/'workspace.json',(old,old))
    item=client.post('/api/maintenance/cleanup',json={'days':30}).json()['items'][0]
    retired=client.post('/api/maintenance/cleanup',json={'days':30,'dry_run':False,'confirmed':True,'selected':{item['job_id']:item['modified']}}).json()['items'][0]
    url='/api/maintenance/retired/'+retired['trash_id']+'/purge'
    assert client.post(url,json={'job_id':folder.name}).status_code==409
    assert client.get('/api/maintenance/retired').json()['items']
    assert client.post(url,json={'job_id':folder.name,'confirmed':True}).status_code==200
    assert client.get('/api/maintenance/retired').json()['items']==[]
    assert server.backups.read(backup['id']).is_file()


def test_saved_case_open_relocates_copy_without_changing_source(api):
    client,folder,server=api
    enterprise=server.enterprise
    enterprise.create_company('ABC010101AB1','Empresa A')
    workspace=load_json_recover(folder/'workspace.json')
    evidence=folder/'evidence_source'/'anexo.txt'
    evidence.parent.mkdir();evidence.write_text('Evidencia')
    workspace['evidence_index']={'records':[{'relative_path':'anexo.txt','source_path':str(evidence)}]}
    atomic_json(folder/'workspace.json',workspace)
    enterprise.create_case('ABC010101AB1','case','Caso A',workspace=workspace,session_dir=folder)
    source=enterprise.case_dir('ABC010101AB1','case')/'session'/'workspace.json'
    original=source.read_bytes()
    response=client.post('/api/cases/ABC010101AB1/case/open')
    assert response.status_code==200
    target=server.WORK/response.json()['job_id']
    record=load_json_recover(target/'workspace.json')['evidence_index']['records'][0]
    assert record['source_path']==str(target/'evidence_source'/'anexo.txt')
    assert source.read_bytes()==original
