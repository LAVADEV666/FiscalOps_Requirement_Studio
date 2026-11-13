from __future__ import annotations
import json, shutil, socket, sys, zipfile, uuid, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from tempfile import TemporaryFile
from persistence import workspace_lock, atomic_json, load_json_recover, session_activity_stamp, session_summary
def now():return datetime.now(timezone.utc).isoformat()
def diagnostic(base:Path,work:Path,enterprise:Path,port:int,ocr_status:dict,ai_status:dict):
 required=['app.py','core.py','word_builder.py','document_model.py','compliance_engine.py','evidence_manager.py','ocr_engine.py','ai_review_engine.py']
 files={name:(base/name).is_file() for name in required};usage=shutil.disk_usage(work);writable=True
 try:
  with TemporaryFile(dir=work) as probe:probe.write(b'ok')
 except Exception:writable=False
 port_free=True
 with socket.socket() as s:
  try:s.bind(('127.0.0.1',port))
  except OSError:port_free=False
 return {'generated_at':now(),'python':sys.version.split()[0],'files':files,'files_ok':all(files.values()),'writable':writable,'disk_free_mb':round(usage.free/1024/1024),'port_free':port_free,'ocr':ocr_status,'ai':ai_status,'work_exists':work.exists(),'enterprise_exists':enterprise.exists(),'work_directory':str(work),'enterprise_directory':str(enterprise)}
def clean_sessions(work:Path,days:int=30,dry_run=True,selected:dict[str,str]|None=None):
 cutoff=datetime.now(timezone.utc)-timedelta(days=days);items=[]
 for d in work.iterdir() if work.exists() else []:
  if not d.is_dir() or d.is_symlink() or len(d.name)!=32 or any(c not in "0123456789abcdef" for c in d.name):continue
  with workspace_lock(d):
   workspace=d/'workspace.json'
   if not d.exists():continue
   stamp=session_activity_stamp(d)
   modified=datetime.fromtimestamp(stamp,timezone.utc)
   if selected is not None and selected.get(d.name)!=modified.isoformat():continue
   if modified<cutoff:
    size=sum(p.stat().st_size for p in d.rglob('*') if p.is_file());items.append({'job_id':d.name,'modified':modified.isoformat(),'size':size})
    if not dry_run:
     items[-1]['trash_id']=retire_session(work,d.name,modified.isoformat())['trash_id']
 return {'dry_run':dry_run,'days':days,'count':len(items),'bytes':sum(x['size'] for x in items),'items':items}

def retire_session(work:Path,job_id:str,expected_modified:str|None=None):
 if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('Sesión inválida.')
 folder=work/job_id
 with workspace_lock(folder):
  root=work.resolve();trash=work/'.trash'/uuid.uuid4().hex
  if folder.is_symlink() or folder.resolve().parent!=root or not trash.resolve().is_relative_to(root):
   raise ValueError('Ruta de depuración inválida.')
  if not folder.is_dir():raise FileNotFoundError('La sesión ya no está disponible.')
  modified=datetime.fromtimestamp(session_activity_stamp(folder),timezone.utc).isoformat()
  if expected_modified is not None and expected_modified!=modified:
   raise ValueError('La sesión cambió en otra ventana. Actualiza la lista antes de retirarla.')
  summary=session_summary(folder)
  item={'job_id':job_id,'removed_at':now(),'label':summary.get('taxpayer_name') or summary.get('source_file') or job_id[:8],'rfc':summary.get('rfc','')}
  trash.mkdir(parents=True)
  atomic_json(trash/'record.json',item)
  shutil.move(str(folder),str(trash/'session'))
  return {**item,'trash_id':trash.name}

def retired_sessions(work:Path):
 items=[]
 for record in (work/'.trash').glob('*/record.json'):
  if (record.parent/'session').is_dir():items.append({**load_json_recover(record),'trash_id':record.parent.name})
 return sorted(items,key=lambda item:item['removed_at'],reverse=True)

def restore_retired(work:Path,trash_id:str):
 if not re.fullmatch(r'[a-f0-9]{32}',trash_id):raise ValueError('Registro inválido.')
 trash=work/'.trash'/trash_id
 if not trash.resolve().is_relative_to(work.resolve()):raise ValueError('Ruta de recuperación inválida.')
 record=load_json_recover(trash/'record.json');job_id=record['job_id']
 if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('Expediente inválido.')
 target=work/job_id;source=trash/'session'
 if target.resolve().parent!=work.resolve() or not source.resolve().is_relative_to(trash.resolve()):raise ValueError('Ruta de recuperación inválida.')
 with workspace_lock(target):
  if target.exists():raise ValueError('Ya existe un expediente con este identificador.')
  shutil.move(str(source),str(target))
 return {'job_id':job_id}

def purge_retired(work:Path,trash_id:str,job_id:str,confirmed:bool):
 if not confirmed or not re.fullmatch(r'[a-f0-9]{32}',trash_id) or not re.fullmatch(r'[a-f0-9]{32}',job_id):
  raise ValueError('Confirma explícitamente el registro que vas a eliminar.')
 root=(work/'.trash').resolve();target=work/'.trash'/trash_id
 # Recursive deletion is limited to one validated, retired record. Active sessions,
 # companies and the separate backup catalog can never be selected by this action.
 if target.is_symlink() or root.parent!=work.resolve() or target.resolve().parent!=root:
  raise ValueError('Ruta de papelera inválida.')
 with workspace_lock(work/job_id):
  record=load_json_recover(target/'record.json')
  if record.get('job_id')!=job_id:raise ValueError('El registro no coincide con la confirmación.')
  shutil.rmtree(target)
 return {'purged':True,'job_id':job_id}
def verify_distribution(root:Path):
 errors=[]
 for p in root.rglob('*.py'):
  try:compile(p.read_text(encoding='utf-8'),str(p),'exec')
  except Exception as exc:errors.append(f'{p.name}: {exc}')
 return {'valid':not errors,'errors':errors,'files':sum(1 for p in root.rglob('*') if p.is_file())}
