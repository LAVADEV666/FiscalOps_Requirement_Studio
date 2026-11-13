import pytest
from compliance_engine import create_matrix,update_row

def data():return {'points':[{'number':1,'requirement_id':'REQ-001','text':'a) Proporcione papel de trabajo en formato Excel.\nb) Aclare las diferencias de CFDI.'}]}
def test_matrix_subitems_and_evidence():
 m=create_matrix(data());assert len(m['rows'])==2;assert 'Excel' in m['rows'][0]['evidence_requested'];assert 'CFDI' in m['rows'][1]['evidence_requested']
def test_completion_requires_document():
 m=create_matrix(data())
 with pytest.raises(ValueError):update_row(m,m['rows'][0]['row_id'],{'status':'completed'})
def test_completed_green():
 m=create_matrix(data());r=update_row(m,m['rows'][0]['row_id'],{'status':'completed','linked_documents':['papel.xlsx'],'responsible':'Luis','due_date':'2026-08-30','risk':'low'});assert r['traffic_light']=='green' and r['score']==100
def test_not_applicable_requires_reason():
 m=create_matrix(data())
 with pytest.raises(ValueError):update_row(m,m['rows'][0]['row_id'],{'status':'not_applicable'})
def test_metrics_recalculated():
 m=create_matrix(data());update_row(m,m['rows'][0]['row_id'],{'status':'in_progress','responsible':'Equipo Fiscal'});assert m['metrics']['completion']>0
