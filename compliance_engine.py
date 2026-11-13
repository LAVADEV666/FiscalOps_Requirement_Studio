from __future__ import annotations
import re
from datetime import date, datetime, timezone
from typing import Any
ITEM_RE=re.compile(r'(?m)^\s*((?:\d{1,2})(?:\.\d+)*|[a-z]\)|[ivx]{1,6}[.)])\s+(.+)',re.I)
ACTION_RULES={'entregar':('entregue','proporcione','aporte','exhiba','remita','acompañe'),'aclarar':('aclare','explique','señale','indique','manifieste'),'conciliar':('concilie','conciliado','cruce','cruzado'),'justificar':('justifique','acredite','demuestre','materialidad')}
EVIDENCE_RULES={'Excel':('excel','xlsx','papel de trabajo'),'CFDI':('cfdi','comprobante fiscal'),'Estado de cuenta':('estado de cuenta','estados de cuenta'),'Contrato':('contrato','convenio'),'Contabilidad':('póliza','poliza','balanza','auxiliar','registro contable'),'Pedimento':('pedimento',),'Comprobante de pago':('transferencia','cheque','comprobante de pago'),'Escrito':('manifestación','escrito libre','informe')}
VALID_STATUS={'pending','in_progress','review','completed','not_applicable'};VALID_RISK={'low','medium','high','critical'}
def now():return datetime.now(timezone.utc).isoformat()
def split_items(text:str):
 found=list(ITEM_RE.finditer(text or ''))
 if not found:return [{'item_id':'main','marker':'','text':str(text or '').strip()}]
 out=[]
 for i,m in enumerate(found):out.append({'item_id':m.group(1).rstrip(').'), 'marker':m.group(1),'text':(m.group(2)+(text[m.end():found[i+1].start()] if i+1<len(found) else text[m.end():])).strip()})
 return out
def classify_action(text):
 folded=text.lower()
 for action,terms in ACTION_RULES.items():
  if any(x in folded for x in terms):return action
 return 'revisar'
def evidence_types(text):
 folded=text.lower();return [k for k,v in EVIDENCE_RULES.items() if any(x in folded for x in v)]
def create_matrix(data:dict[str,Any])->dict[str,Any]:
 rows=[]
 for p in data.get('points',[]):
  rid=p.get('requirement_id') or f"REQ-{int(p['number']):03d}"
  for idx,item in enumerate(split_items(p.get('text','')),1):
   rows.append({'row_id':f'{rid}-{idx:03d}','requirement_id':rid,'numeral':p.get('number'),'subitem':item['marker'],'request_text':item['text'],'required_action':classify_action(item['text']),'evidence_requested':evidence_types(item['text']),'linked_documents':[],'responsible':'[POR DEFINIR]','due_date':'','status':'pending','risk':'high' if not evidence_types(item['text']) else 'medium','notes':'','updated_at':now()})
 matrix={'schema_version':'fiscalops.compliance.v1','rows':rows,'metrics':{}};recalculate(matrix);return matrix
def ensure_matrix(data):
 matrix=data.get('compliance_matrix')
 if not isinstance(matrix,dict) or matrix.get('schema_version')!='fiscalops.compliance.v1':data['compliance_matrix']=create_matrix(data)
 recalculate(data['compliance_matrix']);return data['compliance_matrix']
def row_score(row):
 if row.get('status')=='not_applicable':return 100
 points=0
 if str(row.get('request_text','')).strip():points+=15
 if row.get('required_action') not in ('','revisar'):points+=15
 if row.get('responsible') not in ('','[POR DEFINIR]'):points+=15
 if row.get('due_date'):points+=10
 if row.get('linked_documents'):points+=25
 if row.get('status')=='completed':points+=20
 elif row.get('status')=='review':points+=12
 elif row.get('status')=='in_progress':points+=6
 return min(100,points)
def traffic(row):
 score=row_score(row)
 if row.get('risk')=='critical' or score<35:return 'red'
 if score<70:return 'amber'
 if score<100:return 'yellow'
 return 'green'
def recalculate(matrix):
 rows=matrix.get('rows',[])
 for row in rows:row['score']=row_score(row);row['traffic_light']=traffic(row)
 matrix['metrics']={'total':len(rows),'complete':sum(r['traffic_light']=='green' for r in rows),'red':sum(r['traffic_light']=='red' for r in rows),'amber':sum(r['traffic_light']=='amber' for r in rows),'yellow':sum(r['traffic_light']=='yellow' for r in rows),'completion':round(sum(r['score'] for r in rows)/max(1,len(rows)))};matrix['updated_at']=now()
def validate_update(row):
 if row.get('status') not in VALID_STATUS:raise ValueError('Estatus inválido.')
 if row.get('risk') not in VALID_RISK:raise ValueError('Riesgo inválido.')
 due=row.get('due_date','')
 if due:
  try:date.fromisoformat(due)
  except Exception:raise ValueError('Fecha compromiso inválida.')
 if row.get('status')=='completed' and not row.get('linked_documents'):raise ValueError('No puede cerrarse sin documentos vinculados.')
 if row.get('status')=='not_applicable' and not str(row.get('notes','')).strip():raise ValueError('No aplicable requiere justificación.')
def update_row(matrix,row_id,changes):
 row=next((x for x in matrix.get('rows',[]) if x.get('row_id')==row_id),None)
 if not row:raise KeyError('Fila de cumplimiento no encontrada.')
 allowed={'required_action','evidence_requested','linked_documents','responsible','due_date','status','risk','notes'}
 for k,v in changes.items():
  if k in allowed:row[k]=v
 validate_update(row);row['updated_at']=now();recalculate(matrix);return row
