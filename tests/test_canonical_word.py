from docx import Document
from document_model import build_document
from word_builder import build

def test_canonical_order_and_response(tmp_path):
 out=tmp_path/'canonical.docx'; data={'introduction':'Introducción','points':[{'number':1,'requirement_id':'REQ-001','text':'Requerimiento trazable completo','fragment_ids':['F1'],'asset_ids':[],'response_text':'Respuesta fiscal específica','support_items':['ANEXO 1']}],'assets':[],'metadata_validation':{'fields':{}}}; data['document']=build_document(data); build(data,out,tmp_path); doc=Document(out); text='\n'.join(p.text for p in doc.paragraphs); assert text.index('Requerimiento trazable completo') < text.index('Respuesta fiscal específica') < text.index('ANEXO 1')
