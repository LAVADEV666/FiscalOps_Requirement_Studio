from __future__ import annotations
import re
from datetime import datetime,timezone
from typing import Any
KEYS=('rfc','taxpayer_name','request_type','date','notification_date','deadline','tax','period','amount','authority','administrative_unit')
def now():return datetime.now(timezone.utc).isoformat()
def deterministic_fields(data):return data.get('metadata_validation',{}).get('fields',{})
def normalize_ai(result):
 fields=result.get('fields',{}) if isinstance(result,dict) else {};out={}
 aliases={'razon_social':'taxpayer_name','tipo_requerimiento':'request_type','fecha_oficio':'date','fecha_notificacion':'notification_date','plazo':'deadline'}
 for key,value in fields.items():
  target=aliases.get(key,key);item=value if isinstance(value,dict) else {'value':value}
  out[target]={'value':str(item.get('value','')).strip(),'confidence':float(item.get('confidence',0) or 0),'page':int(item.get('source_page',item.get('pagina',1)) or 1),'source':'ai'}
 return out
def compare(data,ai_result):
 det=deterministic_fields(data);ai=normalize_ai(ai_result);rows=[]
 for key in sorted(set(KEYS)|set(ai)):
  d=det.get(key,{});a=ai.get(key,{});dv=str(d.get('value','')).strip();av=str(a.get('value','')).strip()
  same=re.sub(r'\W','',dv.upper())==re.sub(r'\W','',av.upper()) if dv and av else False
  rows.append({'field':key,'deterministic':{'value':dv,'confidence':float(d.get('confidence',0) or 0),'page':d.get('source_page',1),'source':'deterministic'},'ai':a or {'value':'','confidence':0,'page':1,'source':'ai'},'agreement':same,'decision':'pending','selected_source':'','selected_value':'','reviewed_at':''})
 return {'schema_version':'fiscalops.ai.review.v1','rows':rows,'summary':summary(rows),'created_at':now()}
def summary(rows):return {'total':len(rows),'agreements':sum(r.get('agreement') for r in rows),'pending':sum(r.get('decision')=='pending' for r in rows),'accepted':sum(r.get('decision')=='accepted' for r in rows),'rejected':sum(r.get('decision')=='rejected' for r in rows)}
def decide(review,field,decision,source='',edited_value=''):
 row=next((r for r in review.get('rows',[]) if r.get('field')==field),None)
 if not row:raise KeyError('Campo IA no encontrado.')
 if decision not in {'accepted','rejected','edited'}:raise ValueError('Decisión inválida.')
 if decision=='accepted' and source not in {'ai','deterministic'}:raise ValueError('Fuente inválida.')
 if decision=='edited' and not str(edited_value).strip():raise ValueError('La edición requiere valor.')
 row['decision']=decision;row['selected_source']='human' if decision=='edited' else source if decision=='accepted' else 'deterministic';row['selected_value']=str(edited_value).strip() if decision=='edited' else row.get(source,{}).get('value','') if decision=='accepted' else row['deterministic']['value'];row['reviewed_at']=now();review['summary']=summary(review['rows']);return row
def apply_decisions(data,review):
 fields=deterministic_fields(data);applied=[]
 for row in review.get('rows',[]):
  if row.get('decision') not in {'accepted','edited'}:continue
  value=row.get('selected_value','')
  if not value:continue
  field=fields.setdefault(row['field'],{'name':row['field']});field.update(value=value,valid=True,source=row.get('selected_source','human'),confidence=1.0 if row.get('selected_source')=='human' else row.get(row.get('selected_source'),{}).get('confidence',0),requires_human_review=False);applied.append(row['field'])
 return applied
def analyze_requirements(data):
 items=[]
 for p in data.get('points',[]):
  text=p.get('text','');verbs=[]
  for verb in ('proporcione','entregue','aclare','manifieste','justifique','acredite','concilie'):
   if verb in text.lower():verbs.append(verb)
  evidence=[e.get('type') for e in p.get('requested_evidence',[])]
  items.append({'requirement_id':p.get('requirement_id'),'number':p.get('number'),'summary':text[:350].strip(),'actions':verbs or ['revisión humana'],'evidence':evidence,'confidence':0.65 if verbs else 0.35,'status':'suggestion','human_review_required':True})
 return items
def build_checklist(data):
 result=[]
 for item in analyze_requirements(data):
  result.append({'check_id':f"CHK-{int(item['number']):03d}",'requirement_id':item['requirement_id'],'task':f"Revisar y atender numeral {item['number']}",'actions':item['actions'],'evidence':item['evidence'],'status':'pending','approved_by_human':False})
 return result
