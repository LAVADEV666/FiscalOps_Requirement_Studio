import json,zipfile
from pathlib import Path
from evidence_manager import scan_folder,build_package,verify_package,update_record,validate_file

def test_scan_duplicate_and_numeral(tmp_path):
 (tmp_path/'Numeral_3_estado_cuenta.txt').write_text('evidencia',encoding='utf-8');(tmp_path/'copia.txt').write_text('evidencia',encoding='utf-8');idx=scan_folder(tmp_path);assert idx['metrics']['duplicates']==1;assert any(r['numeral']==3 for r in idx['records'])
def test_invalid_empty(tmp_path):
 p=tmp_path/'vacio.pdf';p.write_bytes(b'');assert validate_file(p)[0] is False
def test_package_preserves_original(tmp_path):
 src=tmp_path/'src';src.mkdir();p=src/'Numeral_1_doc.txt';p.write_text('original',encoding='utf-8');before=p.read_bytes();idx=scan_folder(src);out=tmp_path/'package.zip';result=build_package(idx,out,{'ok':True});assert result['files']==1 and p.read_bytes()==before;assert verify_package(out)['valid']
def test_controlled_rename_only_index(tmp_path):
 p=tmp_path/'doc.txt';p.write_text('abc',encoding='utf-8');idx=scan_folder(tmp_path);r=idx['records'][0];update_record(idx,r['evidence_id'],{'controlled_name':'ANEXO ESPECIAL.txt','numeral':5});assert p.exists() and idx['records'][0]['controlled_name']=='ANEXO_ESPECIAL.txt'
def test_zip_manifest_hash(tmp_path):
 src=tmp_path/'src'
 src.mkdir()
 (src/'req_2.xml').write_text('<x/>',encoding='utf-8')
 idx=scan_folder(src)
 out=tmp_path/'p.zip'
 build_package(idx,out)
 with zipfile.ZipFile(out) as z:
  m=json.loads(z.read('MANIFEST.json'))
 assert m['source_unchanged'] and len(m['files'][0]['sha256'])==64
