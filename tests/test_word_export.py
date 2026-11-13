from docx import Document
from word_builder import build

def test_word_export_contains_metadata(tmp_path):
    out=tmp_path/'test.docx'
    data={'introduction':'Se solicita información.','points':[{'number':1,'text':'Entregue papel de trabajo completo.','asset_ids':[]}], 'assets':[], 'metadata_validation':{'fields':{'rfc':{'value':'ABC010101XX0'},'taxpayer_name':{'value':'EMPRESA DEMO'},'office':{'value':'OF-123'}}}}
    build(data,out,tmp_path); assert out.exists() and out.stat().st_size>1000
    doc=Document(out); text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert 'EMPRESA DEMO' in text and 'ABC010101XX0' in text and 'OF-123' in text
