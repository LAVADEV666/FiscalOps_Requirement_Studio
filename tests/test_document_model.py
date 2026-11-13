from document_model import build_document,validate_document,update_document

def sample(): return {'points':[{'number':1,'requirement_id':'REQ-001','text':'Texto requerido suficientemente amplio','fragment_ids':['F1'],'asset_ids':['A1']}],'assets':[{'asset_id':'A1'}]}
def test_build_and_validate():
 d=sample(); doc=build_document(d); result=validate_document(doc,d); assert result['valid'] and result['block_count']==4
def test_update_syncs_response_and_asset_order():
 d=sample(); d['document']=build_document(d); sec=d['document']['sections'][0]; sec['blocks'][1],sec['blocks'][2]=sec['blocks'][2],sec['blocks'][1]; sec['blocks'][1]['text']='Respuesta desarrollada'; update_document(d,d['document']); assert d['points'][0]['response_text']=='Respuesta desarrollada' and d['points'][0]['asset_ids']==['A1']
def test_invalid_asset_rejected():
 d=sample(); doc=build_document(d); doc['sections'][0]['blocks'][1]['asset_id']='MISSING'; assert not validate_document(doc,d)['valid']
