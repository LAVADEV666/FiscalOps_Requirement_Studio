import pytest
from ai_review_engine import compare,decide,apply_decisions,analyze_requirements,build_checklist

def data():return {'metadata_validation':{'fields':{'rfc':{'value':'ABC010101XX0','confidence':.99},'amount':{'value':'1,000.00','confidence':.8}}},'points':[{'number':1,'requirement_id':'REQ-001','text':'Proporcione papel de trabajo y aclare diferencias.','requested_evidence':[{'type':'excel'}]}]}
def ai():return {'fields':{'rfc':{'value':'ABC010101XX0','confidence':.9,'source_page':1},'amount':{'value':'2,000.00','confidence':.7,'source_page':2}}}
def test_compare_agreement_and_difference():
 r=compare(data(),ai());assert next(x for x in r['rows'] if x['field']=='rfc')['agreement'];assert not next(x for x in r['rows'] if x['field']=='amount')['agreement']
def test_human_decision_and_apply():
 d=data();r=compare(d,ai());decide(r,'rfc','accepted','ai');decide(r,'amount','edited',edited_value='1,500.00');applied=apply_decisions(d,r);assert set(applied)=={'rfc','amount'} and d['metadata_validation']['fields']['amount']['source']=='human'
def test_invalid_decision():
 r=compare(data(),ai())
 with pytest.raises(ValueError):decide(r,'rfc','accepted','internet')
def test_requirements_and_checklist_review_flag():
 items=analyze_requirements(data());checks=build_checklist(data());assert items[0]['human_review_required'] and not checks[0]['approved_by_human'] and 'proporcione' in items[0]['actions']
def test_pending_summary():
 r=compare(data(),ai());assert r['summary']['pending']==len(r['rows'])
