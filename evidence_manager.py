from __future__ import annotations
import hashlib,json,mimetypes,re,shutil,zipfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ALLOWED={'.pdf','.xlsx','.xls','.csv','.docx','.doc','.xml','.txt','.jpg','.jpeg','.png','.zip'}
MAX_FILE=250*1024*1024
MAGIC={'.pdf':b'%PDF-','.zip':b'PK','.docx':b'PK','.xlsx':b'PK','.jpg':b'\xff\xd8\xff','.jpeg':b'\xff\xd8\xff','.png':b'\x89PNG'}
def now():return datetime.now(timezone.utc).isoformat()
def sha256(path:Path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while chunk:=f.read(1024*1024):h.update(chunk)
 return h.hexdigest()
def sanitize(value:str):
 value=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(value));value=re.sub(r'\s+','_',value.strip());value=re.sub(r'_+','_',value)
 return value.strip('._')[:90] or 'ARCHIVO'
def validate_file(path:Path):
 if not path.is_file():return False,'No es archivo.'
 if path.suffix.lower() not in ALLOWED:return False,'Extensión no permitida.'
 if path.stat().st_size==0:return False,'Archivo vacío.'
 if path.stat().st_size>MAX_FILE:return False,'Archivo excede 250 MB.'
 expected=MAGIC.get(path.suffix.lower())
 if expected and not path.read_bytes()[:len(expected)]==expected:return False,'Firma binaria inconsistente.'
 try:
  if path.suffix.lower() in {'.zip','.docx','.xlsx'}:
   with zipfile.ZipFile(path) as z:
    bad=z.testzip()
    if bad:return False,f'Contenedor dañado: {bad}'
 except Exception as exc:return False,f'Contenedor inválido: {exc}'
 return True,'OK'
def infer_numeral(name:str):
 patterns=(r'(?:numeral|num|req)[ _.-]*(\d{1,3})',r'(?:anexo)[ _.-]*(\d{1,3})',r'^0*(\d{1,3})[ _.-]')
 for p in patterns:
  m=re.search(p,name,re.I)
  if m:return int(m.group(1))
 return None
def controlled_name(index:int,numeral:int|None,path:Path):
 stem=sanitize(path.stem);prefix=f'ANEXO_{index:03d}';req=f'_NUMERAL_{numeral:03d}' if numeral is not None else '_GENERAL'
 return f'{prefix}{req}_{stem}{path.suffix.lower()}'
def scan_folder(folder:Path):
 folder=Path(folder)
 if not folder.is_dir():raise ValueError('Carpeta de evidencias no encontrada.')
 records=[];hashes={}
 for index,path in enumerate(sorted((p for p in folder.rglob('*') if p.is_file()),key=lambda x:str(x).lower()),1):
  valid,message=validate_file(path);digest=sha256(path) if valid else ''
  duplicate_of=hashes.get(digest,'') if digest else ''
  if digest and not duplicate_of:hashes[digest]=str(path.relative_to(folder))
  numeral=infer_numeral(path.name)
  records.append({'evidence_id':f'EVD-{index:04d}','source_path':str(path),'relative_path':str(path.relative_to(folder)),'original_name':path.name,'controlled_name':controlled_name(index,numeral,path),'extension':path.suffix.lower(),'size':path.stat().st_size,'sha256':digest,'valid':valid,'validation_message':message,'duplicate':bool(duplicate_of),'duplicate_of':duplicate_of,'numeral':numeral,'classification':'pending' if numeral is None else 'linked','include':valid and not duplicate_of})
 return {'schema_version':'fiscalops.evidence.v1','source_folder':str(folder),'created_at':now(),'records':records,'metrics':metrics(records)}
def metrics(records):return {'total':len(records),'valid':sum(r['valid'] for r in records),'invalid':sum(not r['valid'] for r in records),'duplicates':sum(r['duplicate'] for r in records),'included':sum(r['include'] for r in records),'unassigned':sum(r['numeral'] is None for r in records)}
def update_record(index,evidence_id,changes):
 record=next((r for r in index.get('records',[]) if r['evidence_id']==evidence_id),None)
 if not record:raise KeyError('Evidencia no encontrada.')
 for key in ('numeral','classification','include','controlled_name'):
  if key in changes:record[key]=changes[key]
 if record.get('numeral') is not None:record['numeral']=int(record['numeral'])
 record['controlled_name']=sanitize(Path(record.get('controlled_name','')).stem)+Path(record.get('controlled_name','')).suffix.lower()
 if not record['valid'] or record['duplicate']:record['include']=False
 index['metrics']=metrics(index['records']);return record
def build_package(index:dict[str,Any],out:Path,workspace:dict[str,Any]|None=None):
 out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);selected=[r for r in index.get('records',[]) if r.get('include') and r.get('valid') and not r.get('duplicate')];names=set();manifest=[]
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for r in selected:
   src=Path(r['source_path']);name=r['controlled_name']
   if name in names:raise ValueError(f'Nombre controlado duplicado: {name}')
   names.add(name);z.write(src,'ANEXOS/'+name);manifest.append({k:r.get(k) for k in ('evidence_id','original_name','controlled_name','numeral','classification','size','sha256')})
  payload={'schema_version':'fiscalops.package.v1','created_at':now(),'files':manifest,'source_unchanged':True,'metrics':metrics(index.get('records',[]))}
  z.writestr('MANIFEST.json',json.dumps(payload,ensure_ascii=False,indent=2))
  if workspace is not None:z.writestr('WORKSPACE.json',json.dumps(workspace,ensure_ascii=False,indent=2))
 return {'file':out.name,'sha256':sha256(out),'files':len(selected),'manifest':payload}
def verify_package(path:Path):
 with zipfile.ZipFile(path) as z:
  if 'MANIFEST.json' not in z.namelist():raise ValueError('Paquete sin manifiesto.')
  manifest=json.loads(z.read('MANIFEST.json'));errors=[]
  for item in manifest.get('files',[]):
   name='ANEXOS/'+item['controlled_name']
   if name not in z.namelist():errors.append(f'Falta {name}');continue
   if hashlib.sha256(z.read(name)).hexdigest()!=item['sha256']:errors.append(f'Hash inválido {name}')
  return {'valid':not errors,'errors':errors,'files':len(manifest.get('files',[]))}
