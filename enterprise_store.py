from __future__ import annotations
import hashlib, re, shutil, tempfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from persistence import atomic_json, load_json_recover, workspace_lock, atomic_replace
from workspace_backup import write_backup, restore_archive, rebase_evidence
RFC_RE=re.compile(r'^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$')

def now(): return datetime.now(timezone.utc).isoformat()
def safe_id(value:str)->str:
 value=re.sub(r'[^A-Za-z0-9_-]','_',str(value or '').strip());
 if not value or value in {'.','..'}: raise ValueError('Identificador inválido.')
 return value[:100]
def normalize_rfc(value:str)->str: return re.sub(r'[^A-Z0-9&Ñ]','',str(value or '').upper())
def validate_rfc(value:str)->bool: return bool(RFC_RE.fullmatch(normalize_rfc(value)))
def sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  while chunk:=f.read(1024*1024):h.update(chunk)
 return h.hexdigest()
class EnterpriseStore:
 def __init__(self,base:Path):self.base=Path(base);self.companies=self.base/'companies';self.companies.mkdir(parents=True,exist_ok=True)
 def company_dir(self,rfc:str)->Path:
  rfc=normalize_rfc(rfc)
  if not validate_rfc(rfc):raise ValueError('RFC con estructura inválida.')
  return self.companies/rfc
 def create_company(self,rfc:str,name:str)->dict[str,Any]:
  rfc=normalize_rfc(rfc);d=self.company_dir(rfc);d.mkdir(parents=True,exist_ok=True);(d/'cases').mkdir(exist_ok=True)
  with workspace_lock(d):
   profile=load_json_recover(d/'profile.json') if (d/'profile.json').exists() else {'rfc':rfc,'created_at':now()}
   profile.update(name=str(name).strip() or '[RAZÓN SOCIAL PENDIENTE]',updated_at=now());atomic_json(d/'profile.json',profile);return profile

 def appearance(self,rfc,emoji,color,use_cover=True):
  if emoji not in {'🏢','🏭','🏦','🏪','💼','🌿','⭐','📄'} or not re.fullmatch(r'#[0-9A-Fa-f]{6}',color):
   raise ValueError('Selecciona un icono y color válidos.')
  d=self.company_dir(rfc)
  with workspace_lock(d):
   profile=load_json_recover(d/'profile.json');profile.update(emoji=emoji,color=color,use_cover=use_cover,updated_at=now());atomic_json(d/'profile.json',profile)
  return profile

 def set_cover(self,rfc,content):
  from PIL import Image, ImageOps, UnidentifiedImageError
  if len(content)>4*1024**2:raise ValueError('La portada PNG debe ocupar hasta 4 MB.')
  try:
   with Image.open(BytesIO(content)) as image:
    if image.format!='PNG' or image.width*image.height>16000000:raise ValueError('Usa un PNG de hasta 16 megapíxeles.')
    image.load();cover=ImageOps.fit(image.convert('RGBA'),(1200,480))
  except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
   raise ValueError('No se pudo leer la portada PNG.') from exc
  d=self.company_dir(rfc)
  with workspace_lock(d):
   profile=load_json_recover(d/'profile.json')
   with tempfile.NamedTemporaryFile(dir=d,suffix='.tmp',delete=False) as handle:temporary=Path(handle.name)
   try:
    cover.save(temporary,format='PNG');atomic_replace(temporary,d/'cover.png')
   finally:temporary.unlink(missing_ok=True)
   profile.update(cover_version=sha256(d/'cover.png'),updated_at=now());atomic_json(d/'profile.json',profile)
  return profile

 def list_cases(self,rfc):
  result=[]
  for path in (self.company_dir(rfc)/'cases').glob('*/case.json'):
   if path.resolve().is_relative_to(self.company_dir(rfc).resolve()):result.append(load_json_recover(path))
  return sorted(result,key=lambda item:item.get('updated_at',''),reverse=True)
 def list_companies(self):
  out=[]
  for d in self.companies.iterdir():
   if d.is_dir() and (d/'profile.json').exists():
    try:
     p=load_json_recover(d/'profile.json');p['case_count']=sum(1 for x in (d/'cases').iterdir() if x.is_dir());out.append(p)
    except Exception:pass
  return sorted(out,key=lambda x:x.get('name',''))
 def create_case(self,rfc:str,case_id:str,title:str,source_job_id:str='',*,workspace=None,session_dir=None)->dict[str,Any]:
  company=self.company_dir(rfc);case_id=safe_id(case_id);d=company/'cases'/case_id
  meta={'case_id':case_id,'rfc':normalize_rfc(rfc),'title':str(title).strip() or case_id,'source_job_id':source_job_id,'version':1,'status':'draft','created_at':now(),'updated_at':now()}
  d.parent.mkdir(parents=True,exist_ok=True)
  with workspace_lock(d), tempfile.TemporaryDirectory(dir=d.parent) as temp:
   if d.exists():raise FileExistsError('El expediente ya existe.')
   stage=Path(temp)/'case'
   for name in ('source','workspace','evidence','exports','versions','audit'):
    (stage/name).mkdir(parents=True,exist_ok=True)
   if workspace is not None:
    self._bind(stage,rfc,case_id,workspace,session_dir/'source.pdf' if session_dir else None)
    if session_dir:
     shutil.copytree(session_dir,stage/'session',ignore=lambda directory,names:[
      name for name in names if (Path(directory)/name).is_symlink() or name.endswith('.tmp')
     ])
     rebase_evidence(stage/'session',d/'session',stage/'workspace'/'workspace.json')
     rebase_evidence(stage/'session',d/'session')
   atomic_json(stage/'case.json',meta)
   stage.rename(d)
  return meta
 def case_dir(self,rfc,case_id):
  d=self.company_dir(rfc)/'cases'/safe_id(case_id)
  if not d.is_dir():raise FileNotFoundError('Expediente no encontrado.')
  return d
 def bind_workspace(self,rfc,case_id,workspace:dict,source_pdf:Path|None=None):
  d=self.case_dir(rfc,case_id)
  with workspace_lock(d):
   return self._bind(d,rfc,case_id,workspace,source_pdf)
 def _bind(self,d,rfc,case_id,workspace,source_pdf):
  actual=normalize_rfc(workspace.get('metadata_validation',{}).get('fields',{}).get('rfc',{}).get('value',''))
  if actual and actual!=normalize_rfc(rfc):raise ValueError(f'Cruce de contribuyentes bloqueado: expediente {normalize_rfc(rfc)}, documento {actual}.')
  workspace['enterprise']={'rfc':normalize_rfc(rfc),'case_id':safe_id(case_id),'bound_at':now()};atomic_json(d/'workspace'/'workspace.json',workspace)
  if source_pdf and source_pdf.is_file():shutil.copy2(source_pdf,d/'source'/'source.pdf')
  return {'ok':True,'rfc':normalize_rfc(rfc),'case_id':safe_id(case_id)}
 def snapshot(self,rfc,case_id,label='manual'):
  d=self.case_dir(rfc,case_id);src=d/'workspace'/'workspace.json'
  if not src.exists():raise FileNotFoundError('El expediente no tiene workspace.')
  meta=load_json_recover(d/'case.json');n=int(meta.get('version',1))+1;target=d/'versions'/f'v{n:04d}.json';shutil.copy2(src,target)
  meta.update(version=n,updated_at=now(),last_snapshot_label=str(label));atomic_json(d/'case.json',meta);return {'version':n,'file':target.name,'sha256':sha256(target)}
 def restore(self,rfc,case_id,version:int):
  d=self.case_dir(rfc,case_id);src=d/'versions'/f'v{int(version):04d}.json'
  if not src.exists():raise FileNotFoundError('Versión no encontrada.')
  current=d/'workspace'/'workspace.json'
  if current.exists():shutil.copy2(current,d/'versions'/f'pre_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
  shutil.copy2(src,current);return {'ok':True,'version':int(version),'sha256':sha256(current)}
 def backup(self,rfc,case_id,out:Path):
  d=self.case_dir(rfc,case_id);out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
  with workspace_lock(d):
   manifest=write_backup(d,out,{'rfc':normalize_rfc(rfc),'case_id':safe_id(case_id),'created_at':now()})
  return {'file':out.name,'sha256':sha256(out),'files':len(manifest)}
 def restore_backup(self,zip_path:Path,rfc:str,case_id:str):
  target=self.company_dir(rfc)/'cases'/safe_id(case_id)
  def prepare(staging,destination,manifest):
   if normalize_rfc(manifest.get('rfc',''))!=normalize_rfc(rfc):raise ValueError('El respaldo pertenece a otro RFC.')
   meta=load_json_recover(staging/'case.json')
   if normalize_rfc(meta.get('rfc',''))!=normalize_rfc(rfc):raise ValueError('RFC inconsistente en el respaldo.')
   meta.update(case_id=safe_id(case_id),source_job_id='')
   atomic_json(staging/'case.json',meta,backup=False)
   if (staging/'session').is_dir():
    rebase_evidence(staging/'session',destination/'session',staging/'workspace'/'workspace.json')
    rebase_evidence(staging/'session',destination/'session')
  with workspace_lock(target):
   restore_archive(zip_path,target,prepare)
  return {'ok':True,'rfc':normalize_rfc(rfc),'case_id':safe_id(case_id)}
