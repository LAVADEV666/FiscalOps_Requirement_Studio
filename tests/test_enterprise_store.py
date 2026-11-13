import json,zipfile
import pytest
from enterprise_store import EnterpriseStore

def ws(rfc='ABC010101XX0'):return {'points':[],'metadata_validation':{'fields':{'rfc':{'value':rfc}}}}
def test_company_case_isolation(tmp_path):
 s=EnterpriseStore(tmp_path);s.create_company('ABC010101XX0','Empresa A');s.create_company('DEF010101XX0','Empresa B');s.create_case('ABC010101XX0','OFICIO_1','Caso');s.bind_workspace('ABC010101XX0','OFICIO_1',ws());assert not (tmp_path/'companies'/'DEF010101XX0'/'cases'/'OFICIO_1').exists()
def test_cross_taxpayer_blocked(tmp_path):
 s=EnterpriseStore(tmp_path);s.create_company('ABC010101XX0','A');s.create_case('ABC010101XX0','C1','Caso');
 with pytest.raises(ValueError):s.bind_workspace('ABC010101XX0','C1',ws('DEF010101XX0'))
def test_snapshot_restore(tmp_path):
 s=EnterpriseStore(tmp_path);s.create_company('ABC010101XX0','A');s.create_case('ABC010101XX0','C1','Caso');s.bind_workspace('ABC010101XX0','C1',ws());snap=s.snapshot('ABC010101XX0','C1');assert snap['version']==2;s.restore('ABC010101XX0','C1',2)
def test_backup_manifest_and_restore(tmp_path):
 s=EnterpriseStore(tmp_path/'a');s.create_company('ABC010101XX0','A');s.create_case('ABC010101XX0','C1','Caso');s.bind_workspace('ABC010101XX0','C1',ws());out=tmp_path/'backup.zip';result=s.backup('ABC010101XX0','C1',out);assert result['files']>=2
 with zipfile.ZipFile(out) as z:assert 'MANIFEST.json' in z.namelist()
 t=EnterpriseStore(tmp_path/'b');t.create_company('ABC010101XX0','A');assert t.restore_backup(out,'ABC010101XX0','C2')['ok']
def test_restore_backup_wrong_rfc(tmp_path):
 s=EnterpriseStore(tmp_path/'a');s.create_company('ABC010101XX0','A');s.create_case('ABC010101XX0','C1','Caso');s.bind_workspace('ABC010101XX0','C1',ws());out=tmp_path/'backup.zip';s.backup('ABC010101XX0','C1',out);t=EnterpriseStore(tmp_path/'b');t.create_company('DEF010101XX0','B')
 with pytest.raises(ValueError):t.restore_backup(out,'DEF010101XX0','C1')
