from __future__ import annotations
import json, logging, shutil, uuid, os, signal, threading, time, tempfile, zipfile
from pathlib import Path
from contextvars import ContextVar
from typing import Any, Literal
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from core import extract
from text_normalizer import FiscalOpsNormalizer
from audit_engine import ai_status
from audit_engine import build_fragments, render_pages, validate_integrity, audit_event
from visual_assets import extract_visual_assets
from word_builder import build
from template_store import DOCX_MIME, MAX_TEMPLATE_BYTES, TemplateSlotOccupied, TemplateStore, template_example, template_rfc, load_template, marker_paragraph
from professional_document import revision as document_revision, save_document
from config import VERSION, EDITION, MAX_PDF_MB, MAX_PAGES, ENTERPRISE_DIR, JOB_DIR, PORT, WORK_DIR, CORRECTIONS_DIR, SESSION_RETENTION_DAYS
from persistence import atomic_json, load_json_recover, session_summary, PersistenceError, RevisionConflict, commit_workspace, workspace_history, workspace_lock, restore_workspace
from workspace_backup import MAX_BACKUP, write_backup, restore_archive, rebase_evidence, safe_archive_name
from document_model import ensure_document, update_document, validate_document
from word_audit import compare_document_to_docx, save_report
from enterprise_store import EnterpriseStore, normalize_rfc
from backup_store import BackupStore
from compliance_engine import ensure_matrix, update_row
from evidence_manager import scan_folder, update_record, build_package, verify_package
from ocr_engine import OCREngine
from ai_review_engine import compare as compare_ai, decide as decide_ai, apply_decisions, analyze_requirements, build_checklist
from job_manager import JobManager
from maintenance import diagnostic, clean_sessions, retired_sessions, restore_retired, purge_retired, retire_session
from manual_ocr import MAX_TEXT, MAX_ZONES, Region, apply_reading, read_regions, validate_regions
from processing_pipeline import ProcessingPipeline
from paddle_ocr_engine.human_review import CorrectionsStore
from paddle_ocr_engine.numerals import detect_numerals, sequence_warnings
from paddle_ocr_engine.corrector import OllamaCorrector
from ollama_provider import OllamaClient

BASE=Path(__file__).resolve().parent; WORK=WORK_DIR; WORK.mkdir(parents=True,exist_ok=True)
app=FastAPI(title='FiscalOps Requirement Studio',version=VERSION)
enterprise=EnterpriseStore(ENTERPRISE_DIR)
backups=BackupStore(ENTERPRISE_DIR/'resguardos')
templates=TemplateStore(ENTERPRISE_DIR/'templates')
ocr_service=OCREngine(WORK/'ocr_cache')
jobs=JobManager(JOB_DIR)
RECOVERED_JOBS=jobs.recover_interrupted()
pipeline=ProcessingPipeline(WORK,MAX_PAGES,ocr_service=ocr_service)
ocr_corrections=CorrectionsStore(CORRECTIONS_DIR)
OllamaCorrector.configure_environment();ocr_corrector=OllamaCorrector()
ollama_client=OllamaClient()
app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')
action_revision:ContextVar[int|None]=ContextVar('action_revision',default=None)


@app.middleware('http')
async def no_cache(request:Request,call_next):
    header=request.headers.get('X-Workspace-Revision','')
    token=action_revision.set(int(header) if header.isdecimal() and len(header)<=15 else None)
    try:
        response=await call_next(request)
    finally:
        action_revision.reset(token)
    if request.url.path.startswith(('/static/', '/api/')) or request.url.path in ('/','/audit'):
        response.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma']='no-cache'
    if request.url.path in ('/','/audit'):
        response.headers['Content-Security-Policy']=(
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data: blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
    return response
class Payload(BaseModel): job_id:str; data:dict[str,Any]
class ExportPayload(Payload):
    mode:Literal['draft','reviewed']='draft'
    template_id:str|None=None


class TemplateFormat(BaseModel):
    bold:bool|None=None
    italic:bool|None=None
    underline:bool|None=None
    align:Literal['left','center','right','justify']|None=None
    size:Literal[8,9,10,11,12,14,16,18,20,24,28,32,36,48]|None=None


class TemplateEdit(BaseModel):
    revision:str
    position:int
    fields:dict[str,str]
    formatting:dict[str,TemplateFormat]={}
    ocr_frame:bool|None=None


class TemplateCreate(BaseModel):
    slot:Literal['primer','segundo']
    style:Literal['blank','letter']='letter'


class TemplateIdentity(BaseModel):
    icon:Literal['building','briefcase','factory','shop','bank','leaf','star','document']
    color:str=Field(pattern=r'^#[0-9a-fA-F]{6}$')
class SavePayload(BaseModel): job_id:str; data:dict[str,Any]; event:dict[str,Any]|None=None
class RestoreRevision(BaseModel): expected_revision:int


class OCRRegions(BaseModel):
    regions:list[Region]=Field(min_length=1,max_length=MAX_ZONES)


class OCRRegionPreview(OCRRegions):
    force_ocr:bool=False
    rotation:Literal[0,90,180,270]=0


class OCRRegionApply(OCRRegions):
    expected_revision:int=Field(ge=0)
    requirement_id:str|None=Field(default=None,max_length=80)
    text:str=Field(min_length=1,max_length=MAX_TEXT)


@app.exception_handler(RevisionConflict)
async def revision_conflict(request:Request, error:RevisionConflict):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail":{
        "code":"REVISION_CONFLICT","message":str(error),"revision":error.revision,
    }})


@app.exception_handler(PersistenceError)
async def persistence_error(request:Request,error:PersistenceError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500,content={"detail":{"message":str(error)}})

def job_dir(job_id:str)->Path:
    if len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id): raise HTTPException(400,'Identificador inválido.')
    path=WORK/job_id
    if not path.is_dir() or path.is_symlink() or not path.resolve().is_relative_to(WORK.resolve()): raise HTTPException(404,'Sesión no encontrada.')
    return path

def save_json(path:Path,data:dict): atomic_json(path,data)

def read_workspace(folder:Path):
    with workspace_lock(folder):
        return load_json_recover(folder/'workspace.json')


def commit_action(folder:Path,data:dict):
    expected=action_revision.get()
    if expected is not None and data.get('workspace_revision',0)!=expected:
        raise RevisionConflict(data.get('workspace_revision',0))
    return commit_workspace(folder,data)

@app.get('/')
def home(): return FileResponse(BASE/'static/index.html')
@app.get('/api/health')
def health(): return {'status':'ok','version':VERSION,'edition':EDITION,'ai':ai_status(BASE),'ollama':{'enabled':ollama_client.config.enabled,'endpoint':ollama_client.config.base_url,'model':ollama_client.config.model,'local_only':True},'recovered_jobs':len(RECOVERED_JOBS)}
@app.get('/api/ollama/status')
def ollama_status(): return ollama_client.status()
@app.get('/audit')
def audit_page(): return FileResponse(BASE/'static/audit.html')

@app.post('/api/process-async')
async def process_async(file:UploadFile=File(...),manual_review:bool=Form(False)):
 if not(file.filename or '').lower().endswith('.pdf'):raise HTTPException(400,'Seleccione un PDF.')
 task=jobs.create('pdf_processing');task_dir=JOB_DIR/task['job_id'];input_pdf=task_dir/'input.pdf';size=0
 try:
  with input_pdf.open('wb') as stream:
   while chunk:=await file.read(1048576):
    size+=len(chunk)
    if size>MAX_PDF_MB*1024*1024:raise HTTPException(413,f'Máximo {MAX_PDF_MB} MB.')
    stream.write(chunk)
  if input_pdf.read_bytes()[:5]!=b'%PDF-':raise HTTPException(400,'PDF inválido.')
 except Exception:
  shutil.rmtree(task_dir,ignore_errors=True);raise
 def worker(task_id):
  result=pipeline.run(task_id,input_pdf,lambda stage,pct,msg='':jobs.checkpoint(task_id,stage,pct,msg),recover_ocr=True,allow_manual=manual_review)
  # The completed workspace already has the original PDF and its saved state.
  try:input_pdf.unlink(missing_ok=True)
  except OSError:logging.getLogger('fiscalops.upload').warning('No se pudo retirar el PDF temporal de un trabajo completado.')
  return result
 jobs.run(task['job_id'],worker);return {'task_id':task['job_id'],'status':'queued'}
@app.post('/api/process')
async def process(file:UploadFile=File(...)):
    if not(file.filename or '').lower().endswith('.pdf'): raise HTTPException(400,'Seleccione un PDF.')
    jid=uuid.uuid4().hex; d=WORK/jid; d.mkdir(mode=0o700); pdf=d/'source.pdf'; size=0
    with pdf.open('wb') as stream:
        while chunk:=await file.read(1048576):
            size+=len(chunk)
            if size>MAX_PDF_MB*1024*1024: shutil.rmtree(d); raise HTTPException(413,f'Máximo {MAX_PDF_MB} MB.')
            stream.write(chunk)
    if pdf.read_bytes()[:5]!=b'%PDF-': shutil.rmtree(d); raise HTTPException(400,'PDF inválido.')
    try:
        native_tables={}
        data=FiscalOpsNormalizer.normalize_workspace(extract(pdf,ocr_service,native_tables,recover_ocr=True))
        if int(data.get('pages', 0)) > MAX_PAGES:
            raise ValueError(f'El PDF excede el límite operativo de {MAX_PAGES} páginas.')
        fragments=build_fragments(pdf,data['points'],data.get('ocr_diagnostics',{}).get('pages',[]))
        for point in data['points']:
            rid=f"REQ-{int(point['number']):03d}";point['requirement_id']=rid
            point['fragment_ids']=[x['fragment_id'] for x in fragments if x['requirement_id']==rid]
            point['status']='detected';point['version']=1;point['original_text']=point['text'];point['include']=True
        data['fragments']=fragments
        data['assets']=extract_visual_assets(pdf,d/'assets',data['points'],data.get('ocr_diagnostics',{}).get('pages',[]),native_tables)
        ensure_document(data)
        data['document_validation']=validate_document(data['document'],data)
        ensure_matrix(data)
        data['pages_manifest']=render_pages(pdf,d/'pages')
        data['validation']=validate_integrity(data)
        data['audit_log']=[audit_event('DOCUMENT_PROCESSED')]
        save_json(d/'workspace.json',data);(d/'audit.jsonl').write_text(json.dumps(data['audit_log'][0],ensure_ascii=False)+'\n',encoding='utf-8')
        return {'job_id':jid,'data':data}
    except Exception as exc:
        diagnostic={'error_type':type(exc).__name__,'message':str(exc)}
        (d/'processing_error.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
        raise HTTPException(422,diagnostic)


@app.get('/api/ai/status')
def get_ai_status():
    return ai_status(BASE)

@app.post('/api/ai/analyze/{job_id}')
def ai_analyze(job_id:str):
    d=job_dir(job_id);status=ai_status(BASE)
    if not status.get('available'):
        return {'ok':False,'mode':'deterministic_fallback','status':status,'message':'La aplicación continúa operando con el motor universal determinista. Instale el paquete IA y copie el modelo local para activar Donut.'}
    from ai_engine import FiscalOpsAIEngine
    engine=FiscalOpsAIEngine(BASE/'models'/'donut-docvqa')
    pages=sorted((d/'pages').glob('page-*.png'))
    result=engine.analizar_documento(pages)
    (d/'ai_analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    data=read_workspace(d);review=compare_ai(data,result);data['ai_review']=review;data['ai_requirement_analysis']=analyze_requirements(data);data['ai_checklist']=build_checklist(data);commit_action(d,data)
    return {'ok':True,'mode':'ai','result':result,'review':review,'requirements':data['ai_requirement_analysis'],'checklist':data['ai_checklist']}
@app.get('/api/workspace/{job_id}')
def workspace(job_id:str):
    data=read_workspace(job_dir(job_id));ensure_document(data);data.setdefault('workspace_revision',0);return data
@app.get('/api/hybrid/{job_id}')
def hybrid_status(job_id:str):
    data=read_workspace(job_dir(job_id))
    return {'inspection':data.get('document_inspection',{}),'ocr_decisions':data.get('ocr_decisions',{}),'reconstruction':data.get('reconstruction',{}),'cross_validation':data.get('cross_validation',{}),'fiscal_interpretation':data.get('fiscal_interpretation',{})}
@app.get('/api/pdf/{job_id}')
def pdf(job_id:str): return FileResponse(job_dir(job_id)/'source.pdf',media_type='application/pdf')
@app.get('/api/page/{job_id}/{page}')
def page_image(job_id:str,page:int):
    path=job_dir(job_id)/'pages'/f'page-{page}.png'
    if not path.is_file(): raise HTTPException(404,'Página no encontrada.')
    return FileResponse(path,media_type='image/png')


@app.post('/api/ocr-regions/{job_id}/preview')
def preview_ocr_regions(job_id:str,payload:OCRRegionPreview):
    folder=job_dir(job_id)
    try:
        validate_regions(folder,payload.regions,read_workspace(folder)['pages'])
        readings=read_regions(folder,payload.regions,ocr_service,force_ocr=payload.force_ocr,rotation=payload.rotation)
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(422,str(error)) from error
    return {'readings':readings}


@app.post('/api/ocr-regions/{job_id}/apply')
def apply_ocr_regions(job_id:str,payload:OCRRegionApply):
    folder=job_dir(job_id)
    with workspace_lock(folder):
        data=read_workspace(folder)
        revision=data.get('workspace_revision',0)
        if revision!=payload.expected_revision:
            raise RevisionConflict(revision)
        try:
            validate_regions(folder,payload.regions,data['pages'])
            requirement_id=apply_reading(data,payload.regions,payload.requirement_id,payload.text)
        except ValueError as error:
            raise HTTPException(422,str(error)) from error
        commit_workspace(folder,data,expected=revision)
    return {'requirement_id':requirement_id,'data':data}

@app.get('/api/asset/{job_id}/{name}')
def asset(job_id:str,name:str):
    safe=Path(name).name
    if safe!=name: raise HTTPException(400,'Nombre inválido.')
    path=job_dir(job_id)/'assets'/safe
    if not path.is_file(): raise HTTPException(404,'Recurso no encontrado.')
    return FileResponse(path,media_type='image/png')
@app.get('/api/preview/{job_id}')
def preview(job_id:str):
    data=read_workspace(job_dir(job_id))
    return {'metadata':data.get('metadata_validation',{}),'introduction':data.get('introduction',''),'points':data.get('points',[]),'assets':data.get('assets',[])}
@app.post('/api/save')
def save(payload:SavePayload):
    d=job_dir(payload.job_id);ensure_document(payload.data)
    ensure_matrix(payload.data)
    payload.data['document_validation']=validate_document(payload.data['document'],payload.data)
    if not payload.data['document_validation']['valid']:
        raise HTTPException(409,{'message':'El modelo documental no es válido.','document_validation':payload.data['document_validation']})
    payload.data['validation']=validate_integrity(payload.data)
    event=payload.event or audit_event('WORKSPACE_SAVED');payload.data.setdefault('audit_log',[]).append(event)
    revision=commit_workspace(d,payload.data)
    return {'ok':True,'validation':payload.data['validation'],'workspace_revision':revision}


@app.get('/api/workspace/{job_id}/history')
def history(job_id:str):
    return {'versions':workspace_history(job_dir(job_id))}


@app.post('/api/workspace/{job_id}/history/{revision}')
def restore_revision(job_id:str,revision:int,payload:RestoreRevision):
    try:
        return restore_workspace(job_dir(job_id),revision,payload.expected_revision)
    except FileNotFoundError as exc:
        raise HTTPException(404,str(exc)) from exc


@app.get('/api/workspace/{job_id}/backup')
def backup_workspace(job_id:str):
    folder=job_dir(job_id)
    with tempfile.NamedTemporaryFile(dir=WORK,suffix='.zip',delete=False) as temporary:
        output=Path(temporary.name)
    try:
        with workspace_lock(folder):
            read_workspace(folder)
            write_backup(folder,output,{'schema':'fiscalops.workspace.v1'})
    except (ValueError,OSError,PersistenceError) as exc:
        output.unlink(missing_ok=True)
        raise HTTPException(422,str(exc)) from exc
    return FileResponse(output,filename=f'FiscalOps_Expediente_{job_id[:8]}.zip',
                        background=BackgroundTask(output.unlink,missing_ok=True))


@app.post('/api/workspace/restore')
async def import_workspace(file:UploadFile=File(...)):
    job_id=uuid.uuid4().hex
    def prepare(staging,destination,manifest):
        if manifest.get('schema')!='fiscalops.workspace.v1':
            raise ValueError('Seleccione un respaldo de expediente FiscalOps.')
        data=read_workspace(staging)
        ensure_document(data)
        source=staging/'source.pdf'
        if not source.is_file() or not validate_document(data['document'],data)['valid']:
            raise ValueError('El respaldo no contiene un expediente válido.')
        with source.open('rb') as stream:
            if stream.read(5)!=b'%PDF-':raise ValueError('El PDF original del respaldo no es válido.')
        for page in data.get('pages_manifest',[]):
            name=f"page-{int(page['page'])}.png"
            if not (staging/'pages'/name).is_file():
                raise ValueError(f'Falta la página {page["page"]}.')
        for item in data.get('assets',[]):
            name=item.get('file','')
            if not name or Path(name).name!=name or not (staging/'assets'/name).is_file():
                raise ValueError('Falta un recurso visual del expediente.')
        rebase_evidence(staging,destination)

    try:
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            path=Path(directory)/'incoming.zip'
            size=0
            with path.open('wb') as stream:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_BACKUP:
                        raise ValueError('El respaldo excede 2 GiB.')
                    stream.write(chunk)
            await run_in_threadpool(restore_archive,path,WORK/job_id,prepare)
    except (ValueError,TypeError,KeyError,RuntimeError,OSError,zipfile.BadZipFile) as exc:
        raise HTTPException(422,str(exc)) from exc
    return {'job_id':job_id}
@app.post('/api/validate')
def validate(payload:Payload): return validate_integrity(payload.data)

@app.post('/api/preview-sync')
def preview_sync(payload:Payload):
    # The browser preview is the editable beta surface. This endpoint validates
    # and returns the canonical content that will be used by Word export.
    ensure_document(payload.data)
    ensure_matrix(payload.data)
    payload.data['document_validation']=validate_document(payload.data['document'],payload.data)
    payload.data['validation']=validate_integrity(payload.data)
    return {'ok':True,'points':payload.data.get('points',[]),'assets':payload.data.get('assets',[]),'validation':payload.data['validation']}

@app.post('/api/editor-state')
def editor_state(payload:SavePayload):
    d=job_dir(payload.job_id)
    current=read_workspace(d)
    for key in ('points','assets','editor_state'):
        if key in payload.data: current[key]=payload.data[key]
    if 'document' in payload.data:
        current['document_validation']=update_document(current,payload.data['document'])
    else:
        ensure_document(current)
    revision=commit_workspace(d,current,payload.data.get('workspace_revision',0))
    return {'ok':True,'editor_state':current.get('editor_state',{}),'workspace_revision':revision}

@app.post('/api/new-requirement')
def new_requirement(payload:SavePayload):
    job_dir(payload.job_id)
    return {'ok':True,'redirect':'/'}

class CompanyPayload(BaseModel): rfc:str; name:str
class CasePayload(BaseModel): rfc:str; case_id:str; title:str=''; job_id:str=''
class SnapshotPayload(BaseModel): rfc:str; case_id:str; label:str='manual'
class CleanupPayload(BaseModel):
 days:int=SESSION_RETENTION_DAYS
 dry_run:bool=True
 selected:dict[str,str]|None=None
 confirmed:bool=False
@app.get('/api/jobs/{job_id}')
def job_status(job_id:str):
 try:return jobs.read(job_id)
 except KeyError as exc:raise HTTPException(404,str(exc))
@app.post('/api/jobs/{job_id}/cancel')
def cancel_job(job_id:str):
 try:return jobs.cancel(job_id)
 except KeyError as exc:raise HTTPException(404,str(exc))
@app.get('/api/diagnostic')
def system_diagnostic():return diagnostic(BASE,WORK,ENTERPRISE_DIR,PORT,ocr_service.available(),ai_status(BASE))
@app.post('/api/maintenance/cleanup')
def cleanup(payload:CleanupPayload):
 if payload.days<0:raise HTTPException(400,'La antigüedad no puede ser negativa.')
 if not payload.dry_run and not payload.selected:raise HTTPException(400,'Revise y seleccione las sesiones antes de eliminar.')
 return clean_sessions(WORK,payload.days,payload.dry_run,payload.selected)

class SessionRetire(BaseModel):
 expected_updated_at:str|None=None

@app.post('/api/sessions/{job_id}/retire')
def retire_single_session(job_id:str,payload:SessionRetire):
 try:return retire_session(WORK,job_id,payload.expected_updated_at)
 except (ValueError,OSError,PersistenceError) as exc:raise HTTPException(409,str(exc)) from exc

@app.get('/api/maintenance/retired')
def retired():return {'items':retired_sessions(WORK)}

@app.post('/api/maintenance/retired/{trash_id}/restore')
def undo_retirement(trash_id:str):
 try:return restore_retired(WORK,trash_id)
 except (ValueError,OSError,PersistenceError) as exc:raise HTTPException(409,str(exc)) from exc

class PurgeConfirmation(BaseModel):
 confirmed:bool=False
 job_id:str

@app.post('/api/maintenance/retired/{trash_id}/purge')
def purge_retired_record(trash_id:str,payload:PurgeConfirmation):
 try:return purge_retired(WORK,trash_id,payload.job_id,payload.confirmed)
 except (ValueError,OSError,PersistenceError) as exc:raise HTTPException(409,str(exc)) from exc
class AIReviewDecision(BaseModel): job_id:str; field:str; decision:str; source:str=''; edited_value:str=''
@app.get('/api/ai/review/{job_id}')
def get_ai_review(job_id:str):
 data=read_workspace(job_dir(job_id));return {'review':data.get('ai_review',{'rows':[],'summary':{}}),'requirements':data.get('ai_requirement_analysis',[]),'checklist':data.get('ai_checklist',[])}
@app.post('/api/ai/review/decision')
def ai_review_decision(payload:AIReviewDecision):
 d=job_dir(payload.job_id);data=read_workspace(d);review=data.get('ai_review')
 if not review:raise HTTPException(404,'No existe análisis IA para revisar.')
 try:row=decide_ai(review,payload.field,payload.decision,payload.source,payload.edited_value)
 except (KeyError,ValueError) as exc:raise HTTPException(400,str(exc))
 data.setdefault('audit_log',[]).append(audit_event('AI_FIELD_REVIEWED',before=row['field'],after=row['decision']));commit_action(d,data);return {'ok':True,'row':row,'summary':review['summary']}
@app.post('/api/ai/review/apply/{job_id}')
def apply_ai_review(job_id:str):
 d=job_dir(job_id);data=read_workspace(d);review=data.get('ai_review')
 if not review:raise HTTPException(404,'No existe revisión IA.')
 if review.get('summary',{}).get('pending',0):raise HTTPException(409,'Existen campos IA pendientes de decisión humana.')
 applied=apply_decisions(data,review);data.setdefault('audit_log',[]).append(audit_event('AI_REVIEW_APPLIED',after=','.join(applied)));commit_action(d,data);return {'ok':True,'applied':applied}
@app.post('/api/ai/suggestions/{job_id}')
def ai_suggestions(job_id:str):
 d=job_dir(job_id);data=read_workspace(d);data['ai_requirement_analysis']=analyze_requirements(data);data['ai_checklist']=build_checklist(data);commit_action(d,data);return {'requirements':data['ai_requirement_analysis'],'checklist':data['ai_checklist'],'human_review_required':True}
class OCRRequest(BaseModel): force:bool=False; psm:int|None=None
@app.get('/api/ocr/status')
def ocr_status():return ocr_service.available()
@app.get('/api/ocr/corrector/status')
def ocr_corrector_status():return ocr_corrector.status()
@app.post('/api/ocr/{job_id}/{page}')
def analyze_ocr(job_id:str,page:int,payload:OCRRequest):
 d=job_dir(job_id);path=d/'pages'/f'page-{page}.png'
 if not path.is_file():raise HTTPException(404,'Página no encontrada.')
 try:result=ocr_service.run(path,force=payload.force,psm=payload.psm);result['page']=page
 except Exception as exc:raise HTTPException(422,{'message':'No fue posible ejecutar OCR.','error_type':type(exc).__name__,'detail':str(exc)})
 diagnostics=d/'ocr_diagnostics';diagnostics.mkdir(exist_ok=True);save_json(diagnostics/f'page-{page}.json',result)
 data=read_workspace(d);pages=data.setdefault('ocr_diagnostics',{}).setdefault('pages',[]);old=next((i for i,x in enumerate(pages) if int(x.get('page',0))==page),None)
 if old is None:pages.append(result)
 else:pages[old]=result
 data['ocr_diagnostics']['review_required']=sum(bool(x.get('requires_review')) for x in pages);commit_action(d,data);return result
@app.get('/api/ocr/{job_id}')
def ocr_diagnostics(job_id:str):
 return read_workspace(job_dir(job_id)).get('ocr_diagnostics',{'pages':[],'review_required':0})
class OCRReviewRequest(BaseModel):
 page:int; block_id:str; action:str; corrected_text:str=''
class OCRSuggestionRequest(BaseModel):
 page:int; block_id:str
@app.post('/api/ocr-suggestions/{job_id}')
def suggest_ocr_block(job_id:str,payload:OCRSuggestionRequest):
 d=job_dir(job_id);data=read_workspace(d);pages=data.get('ocr_diagnostics',{}).get('pages',[]);page=next((x for x in pages if int(x.get('page',0))==payload.page),None)
 if not page:raise HTTPException(404,'Página OCR no encontrada.')
 block=next((x for x in page.get('text_blocks',[]) if x.get('block_id')==payload.block_id),None)
 if not block:raise HTTPException(404,'Bloque OCR no encontrado.')
 numeral=next((str(x.get('numeral','')) for x in page.get('numerals',[]) if x.get('block_id')==payload.block_id),'')
 try:suggestion=ocr_corrector.suggest(str(block.get('text','')),numeral)
 except (RuntimeError,ValueError) as exc:raise HTTPException(409,{'message':'Corrector local no disponible.','detail':str(exc)})
 block['ai_suggestion']=suggestion;data.setdefault('audit_log',[]).append(audit_event('OCR_AI_SUGGESTED',before=block.get('text',''),after='Sugerencia local pendiente de revisión'));commit_action(d,data);diagnostics=d/'ocr_diagnostics';diagnostics.mkdir(exist_ok=True);save_json(diagnostics/f'page-{payload.page}.json',page)
 return {'ok':True,'suggestion':suggestion}
@app.post('/api/ocr/review/{job_id}')
def review_ocr_block(job_id:str,payload:OCRReviewRequest):
 if payload.action not in {'confirm','correct','irrelevant'}:raise HTTPException(400,'Acción OCR inválida.')
 d=job_dir(job_id);data=read_workspace(d);pages=data.get('ocr_diagnostics',{}).get('pages',[])
 page=next((x for x in pages if int(x.get('page',0))==payload.page),None)
 if not page:raise HTTPException(404,'Página OCR no encontrada.')
 block=next((x for x in page.get('text_blocks',[]) if x.get('block_id')==payload.block_id),None)
 if not block:raise HTTPException(404,'Bloque OCR no encontrado.')
 original=str(block.get('text',''));corrected=payload.corrected_text.strip()
 if payload.action=='correct' and not corrected:raise HTTPException(400,'La corrección no puede estar vacía.')
 if payload.action=='correct':block.update(text=corrected,confidence=1.0,requires_review=False,review_status='corrected')
 elif payload.action=='confirm':block.update(confidence=1.0,requires_review=False,review_status='confirmed');corrected=original
 else:block.update(requires_review=False,review_status='irrelevant');corrected=''
 active=[x for x in page.get('text_blocks',[]) if x.get('review_status')!='irrelevant']
 page['text']='\n'.join(x.get('text','') for x in active);page['confidence']=round(sum(float(x.get('confidence',0)) for x in active)/max(1,len(active)),4)
 page['numerals']=detect_numerals(active,page.get('width'));page['warnings']=sequence_warnings(page['numerals']);page['requires_review']=any(x.get('requires_review') for x in active) or any(x.get('requires_review') for x in page['numerals']) or bool(page['warnings'])
 entry=ocr_corrections.record({'job_id':job_id,'page':payload.page,'block_id':payload.block_id,'bbox':block.get('bbox',[]),'action':payload.action,'original_text':original,'corrected_text':corrected,'motor':page.get('engine_version','')})
 data['ocr_diagnostics']['review_required']=sum(bool(x.get('requires_review')) for x in pages);data.setdefault('audit_log',[]).append(audit_event('OCR_BLOCK_REVIEWED',before=original,after=corrected));data.setdefault('human_review',{})['required']=any(x.get('requires_review') for x in pages);commit_action(d,data);diagnostics=d/'ocr_diagnostics';diagnostics.mkdir(exist_ok=True);save_json(diagnostics/f'page-{payload.page}.json',page)
 return {'ok':True,'block':block,'page':page,'entry':entry}
class EvidenceUpdate(BaseModel): job_id:str; evidence_id:str; changes:dict[str,Any]
@app.post('/api/evidence/scan/{job_id}')
async def scan_evidence(job_id:str,files:list[UploadFile]=File(...)):
 d=job_dir(job_id)
 with tempfile.TemporaryDirectory(dir=WORK) as temporary:
  uploads=[]
  for item in files:
   safe=Path(item.filename or '').name
   if safe in ('','.','..'):continue
   try:safe_archive_name(safe)
   except ValueError as exc:raise HTTPException(400,'Nombre de evidencia inválido.') from exc
   path=Path(temporary)/str(len(uploads))
   size=0
   with path.open('wb') as stream:
    while chunk:=await item.read(1048576):
     size+=len(chunk)
     if size>250*1024*1024:raise HTTPException(413,f'{safe} excede 250 MB.')
     stream.write(chunk)
   uploads.append((path,safe))
  return await run_in_threadpool(commit_evidence,d,uploads)


def commit_evidence(folder:Path,uploads:list):
    with workspace_lock(folder):
        data=read_workspace(folder)
        expected=action_revision.get()
        if expected is not None and expected!=data.get('workspace_revision',0):
            raise RevisionConflict(data.get('workspace_revision',0))
        target=folder/'evidence_source'
        target.mkdir(exist_ok=True)
        added=[]
        try:
            for source,name in uploads:
                path=target/name
                counter=1
                while path.exists():
                    path=target/f'{Path(name).stem}_{counter}{Path(name).suffix}'
                    counter+=1
                source.rename(path)
                added.append(path)
            index=scan_folder(target)
            previous={item['relative_path']:item for item in data.get('evidence_index',{}).get('records',[])}
            for record in index['records']:
                old=previous.get(record['relative_path'])
                if old and old.get('sha256')==record.get('sha256'):
                    update_record(index,record['evidence_id'],{key:old[key] for key in
                                  ('numeral','classification','include','controlled_name') if key in old})
            data['evidence_index']=index
            commit_action(folder,data)
            return index
        except Exception:
            for path in added:
                path.unlink(missing_ok=True)
            raise
@app.get('/api/evidence/{job_id}')
def get_evidence(job_id:str):
 data=read_workspace(job_dir(job_id));return data.get('evidence_index',{'schema_version':'fiscalops.evidence.v1','records':[],'metrics':{}})
@app.post('/api/evidence/update')
def update_evidence(payload:EvidenceUpdate):
 d=job_dir(payload.job_id);data=read_workspace(d);index=data.get('evidence_index')
 if not index:raise HTTPException(404,'Índice de evidencia inexistente.')
 try:record=update_record(index,payload.evidence_id,payload.changes)
 except (KeyError,ValueError) as exc:raise HTTPException(400,str(exc))
 commit_action(d,data);return {'ok':True,'record':record,'metrics':index['metrics']}
@app.get('/api/evidence/package/{job_id}')
def evidence_package(job_id:str):
 d=job_dir(job_id)
 with workspace_lock(d):
  data=read_workspace(d);index=data.get('evidence_index')
  if not index:raise HTTPException(404,'No existen evidencias indexadas.')
  for record in index['records']:
   if record.get('include') and record.get('valid'):
    source=evidence_file(d,record)
    if source is None:raise HTTPException(409,'Falta un archivo de evidencia en la carpeta del expediente.')
    record['source_path']=str(source)
  name='FiscalOps_Expediente_Anexos.zip'
  out=d/'exports'/f'{uuid.uuid4().hex}_{name}'
  try:
   result=build_package(index,out,data);verification=verify_package(out)
   if not verification['valid']:raise HTTPException(409,{'message':'Los anexos cambiaron después de la revisión.','verification':verification})
   save_json(d/'evidence_package_report.json',{'result':result,'verification':verification})
  except Exception:
   out.unlink(missing_ok=True)
   raise
 return FileResponse(out,filename=name)
class ComplianceUpdate(BaseModel): job_id:str; row_id:str; changes:dict[str,Any]
@app.get('/api/compliance/{job_id}')
def get_compliance(job_id:str):
 d=job_dir(job_id);data=read_workspace(d);matrix=ensure_matrix(data);return matrix
@app.post('/api/compliance/update')
def update_compliance(payload:ComplianceUpdate):
 d=job_dir(payload.job_id);data=read_workspace(d);matrix=ensure_matrix(data)
 try:row=update_row(matrix,payload.row_id,payload.changes)
 except KeyError as exc:raise HTTPException(404,str(exc))
 except ValueError as exc:raise HTTPException(400,str(exc))
 data.setdefault('audit_log',[]).append(audit_event('COMPLIANCE_UPDATED',row.get('requirement_id','')));commit_action(d,data);return {'ok':True,'row':row,'metrics':matrix['metrics']}
@app.get('/api/companies')
def companies(): return {'companies':enterprise.list_companies()}
@app.post('/api/companies')
def create_company(payload:CompanyPayload):
 try:return enterprise.create_company(payload.rfc,payload.name)
 except ValueError as exc:raise HTTPException(400,str(exc))

class CompanyAppearance(BaseModel):
 emoji:str=Field(max_length=8)
 color:str=Field(pattern=r'^#[0-9a-fA-F]{6}$')
 use_cover:bool=True

@app.put('/api/companies/{rfc}/appearance')
def company_appearance(rfc:str,payload:CompanyAppearance):
 try:return enterprise.appearance(rfc,payload.emoji,payload.color,payload.use_cover)
 except (ValueError,PersistenceError) as exc:raise HTTPException(422,str(exc)) from exc

@app.put('/api/companies/{rfc}/cover')
async def company_cover(rfc:str,file:UploadFile=File(...)):
 content=await file.read(4*1024**2+1)
 try:return await run_in_threadpool(enterprise.set_cover,rfc,content)
 except (ValueError,PersistenceError) as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/companies/{rfc}/cover')
def get_company_cover(rfc:str):
 try:path=enterprise.company_dir(rfc)/'cover.png'
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
 if not path.is_file():raise HTTPException(404,'Sin portada.')
 return FileResponse(path,media_type='image/png')

@app.get('/api/companies/{rfc}/identity')
def company_identity(rfc:str):
 try:
  folder=enterprise.company_dir(rfc)
  if not (folder/'profile.json').is_file():return {'rfc':normalize_rfc(rfc),'registered':False}
  profile=load_json_recover(folder/'profile.json')
  cover=profile.get('cover_version') if profile.get('use_cover',True) and (folder/'cover.png').is_file() else None
  return {**{key:profile.get(key) for key in ('rfc','name','emoji','color','updated_at')},'registered':True,'cover_version':cover}
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/companies/{rfc}/cases')
def company_cases(rfc:str):
 try:return {'cases':enterprise.list_cases(rfc)}
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.post('/api/cases/{rfc}/{case_id}/open')
def open_company_case(rfc:str,case_id:str):
 try:
  case=enterprise.case_dir(rfc,case_id)
  with workspace_lock(case):
   meta=load_json_recover(case/'case.json');existing=meta.get('source_job_id','')
   if len(existing)==32 and all(c in '0123456789abcdef' for c in existing) and (WORK/existing/'workspace.json').is_file():
    workspace=read_workspace(WORK/existing)
    actual=workspace.get('metadata_validation',{}).get('fields',{}).get('rfc',{}).get('value','')
    if normalize_rfc(actual)==normalize_rfc(rfc):return {'job_id':existing}
   source=case/'session'
   if not (source/'workspace.json').is_file():raise ValueError('Este registro aún no tiene un PDF asociado.')
   job_id=uuid.uuid4().hex;target=WORK/job_id
   shutil.copytree(source,target)
   rebase_evidence(target,target)
   meta['source_job_id']=job_id;atomic_json(case/'case.json',meta)
   return {'job_id':job_id}
 except (ValueError,FileNotFoundError) as exc:raise HTTPException(422,str(exc)) from exc
@app.post('/api/cases')
def create_case(payload:CasePayload):
 try:
  if payload.job_id:
   d=job_dir(payload.job_id)
   with workspace_lock(d):
    return enterprise.create_case(payload.rfc,payload.case_id,payload.title,payload.job_id,workspace=read_workspace(d),session_dir=d)
  return enterprise.create_case(payload.rfc,payload.case_id,payload.title)
 except FileExistsError as exc:raise HTTPException(409,str(exc))
 except ValueError as exc:raise HTTPException(400,str(exc))
@app.post('/api/cases/snapshot')
def snapshot_case(payload:SnapshotPayload):
 try:return enterprise.snapshot(payload.rfc,payload.case_id,payload.label)
 except (ValueError,FileNotFoundError) as exc:raise HTTPException(404,str(exc))
@app.post('/api/cases/{rfc}/{case_id}/restore/{version}')
def restore_case(rfc:str,case_id:str,version:int):
 try:return enterprise.restore(rfc,case_id,version)
 except (ValueError,FileNotFoundError) as exc:raise HTTPException(404,str(exc))
@app.get('/api/cases/{rfc}/{case_id}/backup')
def backup_case(rfc:str,case_id:str):
 with tempfile.NamedTemporaryFile(dir=WORK,suffix='.zip',delete=False) as temporary:
  out=Path(temporary.name)
 try:
  enterprise.backup(rfc,case_id,out)
 except (ValueError,OSError) as exc:
  out.unlink(missing_ok=True);raise HTTPException(404,str(exc)) from exc
 return FileResponse(out,filename=f'FiscalOps_Backup_{normalize_rfc(rfc)}.zip',
                     background=BackgroundTask(out.unlink,missing_ok=True))
@app.get('/api/sessions')
def sessions():
    items=[session_summary(p) for p in WORK.iterdir() if p.is_dir() and len(p.name)==32]
    return {'sessions':sorted(items,key=lambda x:x.get('updated_at',''),reverse=True)}

class SessionOrganization(BaseModel):
    pinned:bool=False
    archived:bool=False
    group:str=Field(default='',max_length=60)

@app.put('/api/sessions/{job_id}/organization')
def organize_session(job_id:str,payload:SessionOrganization):
    folder=job_dir(job_id)
    with workspace_lock(folder):atomic_json(folder/'library.json',payload.model_dump())
    return payload.model_dump()

class BackupCreate(BaseModel):
    job_id:str
    title:str=Field(default='',max_length=160)

class BackupOrganization(BaseModel):
    title:str=Field(max_length=160)
    archived:bool=False

@app.get('/api/backups')
def list_backups():return {'backups':backups.list()}

@app.post('/api/backups')
def create_managed_backup(payload:BackupCreate):
    try:return backups.create(job_dir(payload.job_id),payload.title)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/backups/{backup_id}/file')
def managed_backup_file(backup_id:str):
    try:path=backups.read(backup_id)
    except (ValueError,OSError,PersistenceError) as exc:raise HTTPException(422,str(exc)) from exc
    return FileResponse(path,filename='FiscalOps_Resguardo_'+backup_id[:8]+'.zip',media_type='application/zip')

@app.put('/api/backups/{backup_id}')
def organize_backup(backup_id:str,payload:BackupOrganization):
    try:return backups.organize(backup_id,payload.title,payload.archived)
    except (ValueError,OSError,PersistenceError) as exc:raise HTTPException(422,str(exc)) from exc
@app.post('/api/recover/{job_id}')
def recover_session(job_id:str):
    d=job_dir(job_id); data=read_workspace(d)
    data.setdefault('audit_log',[]).append(audit_event('SESSION_RECOVERED'))
    commit_action(d,data)
    return {'ok':True,'job_id':job_id,'data':data}
@app.post('/api/shutdown')
def shutdown_server():
    def stop(): time.sleep(.35);os.kill(os.getpid(),signal.SIGINT)
    threading.Thread(target=stop,daemon=True).start()
    return {'ok':True}


def template_call(action, *args):
    try:
        return action(*args)
    except FileNotFoundError as exc:
        raise HTTPException(404,'Plantilla no encontrada para ese RFC.') from exc
    except TemplateSlotOccupied as exc:
        raise HTTPException(409,str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(423,'No se pudo reemplazar el archivo. Verifica sus permisos o si está en uso; el original se conserva.') from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@app.get('/api/template-example')
def example_template():
    return Response(template_example(), media_type=DOCX_MIME,
                    headers={'Content-Disposition':'attachment; filename="Plantilla_FiscalOps.docx"'})


@app.get('/api/templates/{rfc}')
def list_templates(rfc:str,include_legacy:bool=False):
    result={'templates':template_call(templates.list,rfc)}
    if include_legacy:
        result['legacy']=template_call(templates.legacy,rfc)
    return result


@app.post('/api/templates/{rfc}')
async def import_template(rfc:str, slot:str=Form(...), file:UploadFile=File(...)):
    content=await read_template_upload(file)
    return await run_in_threadpool(template_call,templates.save,rfc,slot,content)


@app.post('/api/templates/{rfc}/create')
def create_template(rfc:str,payload:TemplateCreate):
    return template_call(templates.create,rfc,payload.slot,payload.style)


@app.get('/api/template-profiles/{rfc}')
def template_identity(rfc:str):
    return template_call(templates.profile,rfc)


@app.get('/api/template-profiles')
def template_library():
    return {'customers':templates.library()}


@app.put('/api/template-profiles/{rfc}')
def set_template_identity(rfc:str,payload:TemplateIdentity):
    return template_call(templates.set_profile,rfc,payload.icon,payload.color)


async def read_template_upload(file:UploadFile):
    if Path(file.filename or '').suffix.lower()!='.docx':
        raise HTTPException(422,'Selecciona un archivo DOCX de Word.')
    content=await file.read(MAX_TEMPLATE_BYTES+1)
    if len(content)>MAX_TEMPLATE_BYTES:
        raise HTTPException(413,'La plantilla excede 20 MB.')
    return content


@app.get('/api/templates/{rfc}/{template_id}')
def get_template(rfc:str,template_id:str):
    return template_call(templates.details,rfc,template_id)


@app.put('/api/templates/{rfc}/{template_id}')
def edit_template(rfc:str,template_id:str,payload:TemplateEdit):
    formatting={key:value.model_dump(exclude_none=True) for key,value in payload.formatting.items()}
    return template_call(templates.edit,rfc,template_id,payload.revision,payload.position,payload.fields,formatting,payload.ocr_frame)


@app.put('/api/templates/{rfc}/{template_id}/file')
async def replace_template(rfc:str,template_id:str,revision:str=Form(...),file:UploadFile=File(...)):
    content=await read_template_upload(file)
    return await run_in_threadpool(template_call,templates.save,rfc,template_id,content,revision)


@app.put('/api/templates/{rfc}/{template_id}/wordcraft')
async def save_wordcraft_template(rfc:str,template_id:str,revision:str=Form(...),file:UploadFile=File(...)):
    content=await read_template_upload(file)
    # A full editor may delete the anchor. Never silently move OCR content to the end.
    doc=template_call(load_template,content)
    template_call(marker_paragraph,doc)
    return await run_in_threadpool(template_call,templates.save,rfc,template_id,content,revision)


@app.get('/api/wordcraft/{job_id}/state')
def professional_state(job_id:str):
    folder=job_dir(job_id)
    with workspace_lock(folder):
        path=folder/'wordcraft'/'document.docx'
        return {'saved':path.exists(),'revision':document_revision(path)}


@app.get('/api/wordcraft/{job_id}/document')
def professional_document(job_id:str,fresh:bool=False,template_id:Literal['primer','segundo']|None=None):
    folder=job_dir(job_id)
    with workspace_lock(folder):
        workspace=read_workspace(folder)
        path=folder/'wordcraft'/'document.docx'
        revision=document_revision(path)
        if path.exists() and not fresh:
            content=path.read_bytes()
        else:
            template=None
            if template_id:
                rfc=workspace.get('metadata_validation',{}).get('fields',{}).get('rfc',{}).get('value','')
                template=template_call(templates.read,str(rfc),template_id)
            with tempfile.TemporaryDirectory(dir=folder) as temp:
                output=Path(temp)/'document.docx'
                build(workspace,output,folder/'assets',template=template)
                content=output.read_bytes()
        return Response(content,media_type=DOCX_MIME,headers={
            'X-Document-Revision':revision,'X-Workspace-Revision':str(workspace.get('workspace_revision',0)),
            'Content-Disposition':'attachment; filename="Escrito_WordCraft.docx"'})


@app.put('/api/wordcraft/{job_id}/document')
async def save_professional_document(job_id:str,revision:str=Form(''),file:UploadFile=File(...)):
    folder=job_dir(job_id)
    content=await read_template_upload(file)
    def store():
        with workspace_lock(folder):
            result=template_call(save_document,folder/'wordcraft'/'document.docx',content,revision)
            return {'revision':result}
    return await run_in_threadpool(store)


@app.get('/api/templates/{rfc}/legacy/{template_id}')
def download_legacy_template(rfc:str,template_id:str):
    content=template_call(templates.read_legacy,rfc,template_id)
    return Response(content,media_type=DOCX_MIME,
                    headers={'Content-Disposition':'attachment; filename="Plantilla_anterior_FiscalOps.docx"'})


@app.get('/api/templates/{rfc}/{template_id}/file')
def download_template(rfc:str,template_id:str):
    content=template_call(templates.read,rfc,template_id)
    return Response(content,media_type=DOCX_MIME,
                    headers={'Content-Disposition':'attachment; filename="Plantilla_FiscalOps.docx"'})


@app.post('/api/export')
def export(payload:ExportPayload):
    d=job_dir(payload.job_id)
    with workspace_lock(d):
        data=payload.data
        if payload.mode=='reviewed' or payload.template_id:
            data=read_workspace(d)
            revision=data.get('workspace_revision',0)
            if revision!=payload.data.get('workspace_revision',0):
                raise RevisionConflict(revision)
        if payload.mode=='reviewed':
            pending=review_items(data,d)
            if pending:raise HTTPException(409,{'message':'Completa la revisión antes de exportar.','items':pending})
        template=None
        if payload.template_id:
            rfc=data.get('metadata_validation',{}).get('fields',{}).get('rfc',{}).get('value','')
            template=template_call(templates.read,str(rfc),payload.template_id)
        return build_export(d,data,payload.mode,template)


def review_items(data:dict, folder:Path) -> list[dict]:
    ensure_document(data)
    fields=data.get('metadata_validation',{}).get('fields',{})
    items=[{'label':alert['message'],'tab':'validation'} for alert in validate_integrity(data)['alerts']
           if alert.get('severity')=='critical']
    for key,label in [('rfc','RFC'),('office','número de oficio')]:
        field=fields.get(key,{})
        value=str(field.get('value','')).strip()
        valid=FiscalOpsNormalizer.validate_rfc(value) if key=='rfc' else bool(value and not value.startswith('['))
        if not valid or field.get('reviewed_value')!=value:
            items.append({'label':f'Confirma el {label} con el PDF original.','tab':'metadata','field':key})
    records=data.get('evidence_index',{}).get('records',[])
    for point in data.get('points',[]):
        rid=point['requirement_id']
        number=point['number']
        if point.get('status')!='validated':
            items.append({'label':f'Valida el texto del numeral {number}.','tab':'requirements','rid':rid})
        response=point.get('response_text','').strip()
        if not response or '[DESARROLLAR RESPUESTA]' in response:
            items.append({'label':f'Redacta la respuesta al numeral {number}.','tab':'preview','rid':rid})
        supports=point.get('support_items',[])
        if any(str(item).strip().startswith('[') for item in supports):
            items.append({'label':f'Completa o retira los marcadores de anexos del numeral {number}.','tab':'preview','rid':rid})
        linked=[
            record for record in records if
            record.get('include') and record.get('valid') and record.get('numeral')==number
            and evidence_file(folder,record)
        ]
        if (point.get('requested_evidence') or supports) and not linked:
            items.append({'label':f'Verifica y vincula los anexos del numeral {number}.','tab':'evidence','rid':rid})
        elif linked:
            names={str(record.get(key,'')).strip().casefold() for record in linked
                   for key in ('controlled_name','original_name') if record.get(key)}
            missing=[item for item in supports if not str(item).startswith('[') and str(item).strip().casefold() not in names]
            if missing:
                items.append({'label':f'Identifica cada anexo del numeral {number} por su nombre de archivo vinculado.','tab':'preview','rid':rid})
    return items


def evidence_file(folder:Path,record:dict) -> Path|None:
    try:
        path=(folder/'evidence_source'/str(record.get('relative_path',''))).resolve()
        if path.is_relative_to((folder/'evidence_source').resolve()) and path.is_file():
            return path
    except OSError:
        pass
    return None


@app.get('/api/workspace/{job_id}/export-review')
def review_export(job_id:str):
    folder=job_dir(job_id)
    data=read_workspace(folder)
    return {'items':review_items(data,folder),'workspace_revision':data.get('workspace_revision',0)}


def build_export(d:Path,data:dict,mode:str,template:bytes|None=None):
    ensure_document(data)
    if mode=='draft':
        for section in data['document'].get('sections',[]):
            for block in section.get('blocks',[]):
                if block.get('type')=='support_list' and block.get('items')==['[ANEXO]','[NOMBRE DEL ARCHIVO]','[DESCRIPCIÓN]']:
                    block['items']=[]
    doc_validation=validate_document(data['document'],data)
    if not doc_validation['valid']: raise HTTPException(409,{'message':'El modelo documental no es válido.','document_validation':doc_validation})
    validation=validate_integrity(data)
    critical=[alert['message'] for alert in validation.get('alerts',[]) if alert.get('severity')=='critical']
    if critical:
        raise HTTPException(409,{'message':' '.join(critical),'validation':validation})
    exports=d/'exports'
    exports.mkdir(exist_ok=True)
    name=('Contestacion_FiscalOps_Plantilla.docx' if template else
          'Contestacion_FiscalOps_Revisada.docx' if mode=='reviewed' else 'Contestacion_FiscalOps_Borrador.docx')
    out=exports/f'{uuid.uuid4().hex}_{name}'
    try:
        build(data,out,d/'assets',export_mode=mode,template=template)
        if not out.is_file() or out.stat().st_size<1000: raise ValueError('Documento incompleto.')
        comparison=compare_document_to_docx(data,out)
        comparison.update(mode=mode,workspace_revision=data.get('workspace_revision',0))
        save_json(d/'word_comparison.json',comparison)
    except Exception as exc:
        out.unlink(missing_ok=True)
        raise HTTPException(500,{'message':'No fue posible generar Word.','error_type':type(exc).__name__}) from exc
    if not comparison['valid']:
        out.unlink(missing_ok=True)
        raise HTTPException(500,{'message':'El Word no coincide con el modelo documental.','comparison':comparison})
    return FileResponse(out,filename=name)
@app.get('/api/word-comparison/{job_id}')
def word_comparison(job_id:str):
    d=job_dir(job_id);path=d/'word_comparison.json'
    if not path.is_file(): raise HTTPException(404,'Aún no existe una comparación Word.')
    return json.loads(path.read_text(encoding='utf-8'))
@app.post('/api/export-json')
def export_json(payload:Payload):
    d=job_dir(payload.job_id)
    with workspace_lock(d):
        exports=d/'exports'
        exports.mkdir(exist_ok=True)
        out=exports/f'{uuid.uuid4().hex}_Auditoria_Integral_SAT.json'
        save_json(out,payload.data)
    return FileResponse(out,filename='Auditoria_Integral_SAT.json')
