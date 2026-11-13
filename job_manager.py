from __future__ import annotations
import json, threading, traceback, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from persistence import atomic_json
TERMINAL={'completed','failed','cancelled'}
def now():return datetime.now(timezone.utc).isoformat()
class JobCancelled(RuntimeError):pass
class JobManager:
 def __init__(self,base:Path):self.base=Path(base);self.base.mkdir(parents=True,exist_ok=True);self._lock=threading.RLock();self._cancel={}
 def path(self,jid):return self.base/jid/'job.json'
 def create(self,kind='process'):
  jid=uuid.uuid4().hex;state={'job_id':jid,'kind':kind,'status':'queued','stage':'queued','progress':0,'message':'En espera','created_at':now(),'updated_at':now(),'error':None,'result':None};atomic_json(self.path(jid),state,backup=False);self._cancel[jid]=threading.Event();return state
 def read(self,jid):
  p=self.path(jid)
  with self._lock:
   if not p.exists():raise KeyError('Trabajo no encontrado.')
   try:return json.loads(p.read_text(encoding='utf-8'))
   except FileNotFoundError:
    if not p.exists():raise KeyError('Trabajo no encontrado.')
    return json.loads(p.read_text(encoding='utf-8'))
 def update(self,jid,**changes):
  with self._lock:
   state=self.read(jid);state.update(changes,updated_at=now());atomic_json(self.path(jid),state);return state
 def cancelled(self,jid):return self._cancel.setdefault(jid,threading.Event()).is_set()
 def checkpoint(self,jid,stage,progress,message=''):
  if self.cancelled(jid):self.update(jid,status='cancelled',stage='cancelled',message='Cancelado de forma segura');raise JobCancelled('Trabajo cancelado.')
  return self.update(jid,status='running',stage=stage,progress=max(0,min(100,int(progress))),message=message or stage)
 def cancel(self,jid):
  state=self.read(jid)
  if state['status'] in TERMINAL:return state
  self._cancel.setdefault(jid,threading.Event()).set();return self.update(jid,status='cancelling',message='Cancelación solicitada')
 def run(self,jid,worker:Callable[...,Any],*args,**kwargs):
  def wrapped():
   try:
    self.checkpoint(jid,'starting',1,'Iniciando');result=worker(jid,*args,**kwargs)
    if not self.cancelled(jid):self.update(jid,status='completed',stage='completed',progress=100,message='Completado',result=result)
   except JobCancelled:pass
   except Exception as exc:self.update(jid,status='failed',stage='failed',message='Error controlado',error={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc(limit=8)})
  threading.Thread(target=wrapped,daemon=True,name=f'fiscalops-{jid[:8]}').start();return self.read(jid)
 def recover_interrupted(self):
  recovered=[]
  for p in self.base.glob('*/job.json'):
   try:
    state=json.loads(p.read_text(encoding='utf-8'))
    if state.get('status') in {'queued','running','cancelling'}:state.update(status='interrupted',stage='recovery',message='Interrumpido por cierre previo; puede reintentarse',updated_at=now());atomic_json(p,state);recovered.append(state['job_id'])
   except Exception:continue
  return recovered
