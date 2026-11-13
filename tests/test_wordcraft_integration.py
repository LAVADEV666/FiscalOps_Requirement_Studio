from io import BytesIO

from docx import Document
import pytest

from persistence import atomic_json
from professional_document import revision, save_document
from template_store import MARKER, TemplateSlotOccupied, TemplateStore, as_bytes, marker_paragraph
from word_builder import build


def test_creation_identity_and_ocr_frame_export(tmp_path):
    store = TemplateStore(tmp_path / 'templates')
    rfc = 'ABC010101AB1'
    item = store.create(rfc, 'primer', 'blank')
    assert item['position'] == 1
    assert store.library()[0]['rfc'] == rfc
    assert store.set_profile(rfc, 'factory', '#224466') == store.profile(rfc)
    assert store.profile('DEF010101CD2')['icon'] == 'building'
    with pytest.raises(ValueError):
        store.set_profile(rfc, 'unknown', '#224466')
    with pytest.raises(TemplateSlotOccupied):
        store.create(rfc, 'primer')
    item = store.edit(rfc, 'primer', item['revision'], 0, {}, ocr_frame=True)
    assert item['ocr_frame']
    doc = Document(BytesIO(store.read(rfc, 'primer')))
    assert len(marker_paragraph(doc)._p.xpath('./w:pPr/w:pBdr/*')) == 4
    out = tmp_path / 'result.docx'
    build({'points':[{'number':1, 'text':'Contenido OCR en el destino elegido.'}]}, out, template=store.read(rfc, 'primer'))
    text = '\n'.join(p.text for p in Document(out).paragraphs)
    assert 'Contenido OCR en el destino elegido.' in text
    assert MARKER not in text
    item = store.edit(rfc, 'primer', item['revision'], 1, {}, ocr_frame=False)
    assert not item['ocr_frame']


def test_professional_document_rejects_stale_save_and_preserves_rich_content(tmp_path):
    path = tmp_path / 'wordcraft' / 'document.docx'
    doc = Document()
    doc.add_paragraph('Escrito profesional').runs[0].bold = True
    doc.add_table(rows=1, cols=2).cell(0, 0).text = 'Tabla editada'
    version = save_document(path, as_bytes(doc), '')
    assert version == revision(path)
    original = path.read_bytes()
    doc.add_paragraph('Cambios de otra sesión')
    with pytest.raises(ValueError, match='otra sesión'):
        save_document(path, as_bytes(doc), '')
    assert path.read_bytes() == original
    save_document(path, as_bytes(doc), version)
    reopened = Document(path)
    assert reopened.paragraphs[0].runs[0].bold
    assert reopened.tables[0].cell(0, 0).text == 'Tabla editada'
    assert reopened.paragraphs[-1].text == 'Cambios de otra sesión'


def test_professional_package_is_preserved_in_workspace_backup(tmp_path):
    from workspace_backup import write_backup, restore_archive
    folder = tmp_path / 'workspace'
    atomic_json(folder / 'workspace.json', {'workspace_revision':0})
    doc = Document()
    doc.add_paragraph('Documento con formato y comentarios de WordCraft')
    content = as_bytes(doc)
    path = folder / 'wordcraft' / 'document.docx'
    save_document(path, content, '')
    assert path.read_bytes() == content
    archive = tmp_path / 'backup.zip'
    write_backup(folder, archive, {'schema':'fiscalops.workspace.v1'})
    restored = tmp_path / 'restored'
    def prepare(staging, destination, manifest):
        assert manifest['schema'] == 'fiscalops.workspace.v1'
    restore_archive(archive, restored, prepare)
    assert (restored / 'wordcraft' / 'document.docx').read_bytes() == content


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, 'templates', TemplateStore(tmp_path / 'templates'))
    monkeypatch.setattr(server, 'WORK', tmp_path / 'work')
    folder = server.WORK / ('a' * 32)
    folder.mkdir(parents=True)
    atomic_json(folder / 'workspace.json', {'workspace_revision':0, 'points':[{'number':1,'text':'Numeral OCR completo.'}]})
    with TestClient(server.app) as test_client:
        yield test_client, folder


def test_template_api_roundtrip_and_missing_anchor_is_rejected(client):
    api, _ = client
    url = '/api/templates/ABC010101AB1'
    response = api.post(url + '/create', json={'slot':'segundo','style':'letter'})
    assert response.status_code == 200
    item = response.json()
    doc = Document()
    doc.add_paragraph('Sin el punto de inserción OCR')
    response = api.put(url + '/segundo/wordcraft', data={'revision':item['revision']}, files={'file':('p.docx',as_bytes(doc))})
    assert response.status_code == 422
    doc.add_paragraph(MARKER)
    response = api.put(url + '/segundo/wordcraft', data={'revision':item['revision']}, files={'file':('p.docx',as_bytes(doc))})
    assert response.status_code == 200
    assert api.get(url + '/segundo').json()['revision'] == response.json()['revision']
    assert api.post(url + '/create',json={'slot':'segundo'}).status_code == 409
    assert api.get('/api/template-profiles').json()['customers'][0]['rfc'] == 'ABC010101AB1'
    response = api.put('/api/template-profiles/ABC010101AB1',json={'icon':'star','color':'#118844'})
    assert response.status_code == 200
    assert api.get('/api/template-profiles/ABC010101AB1').json()['icon'] == 'star'


def test_professional_api_saves_without_changing_ocr_workspace(client):
    api, folder = client
    url = '/api/wordcraft/' + ('a' * 32)
    original = (folder / 'workspace.json').read_bytes()
    response = api.get(url + '/document')
    assert response.status_code == 200
    assert response.headers['x-document-revision'] == ''
    doc = Document(BytesIO(response.content))
    doc.add_paragraph('Respuesta diseñada en WordCraft')
    content = as_bytes(doc)
    response = api.put(url + '/document',data={'revision':''},files={'file':('escrito.docx',content)})
    assert response.status_code == 200
    assert api.get(url + '/state').json()['saved']
    reopened = Document(BytesIO(api.get(url + '/document').content))
    assert reopened.paragraphs[-1].text == 'Respuesta diseñada en WordCraft'
    assert (folder / 'workspace.json').read_bytes() == original
    assert api.put(url + '/document',data={'revision':''},files={'file':('escrito.docx',content)}).status_code == 422
    fresh = Document(BytesIO(api.get(url + '/document?fresh=true').content))
    assert 'Respuesta diseñada en WordCraft' not in '\n'.join(p.text for p in fresh.paragraphs)


def test_local_wordcraft_is_served_with_wasm_mime(client):
    from pathlib import Path
    api, _ = client
    page = api.get('/static/vendor/wordcraft/wordcraft-web-0.14.0/index.html')
    assert page.status_code == 200
    root = Path(__file__).resolve().parents[1] / 'static/vendor/wordcraft/wordcraft-web-0.14.0'
    wasm = next(root.glob('*.wasm'))
    response = api.get('/static/vendor/wordcraft/wordcraft-web-0.14.0/' + wasm.name)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/wasm'
    assert response.content.startswith(b'\x00asm')
