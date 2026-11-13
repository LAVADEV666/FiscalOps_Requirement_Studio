from __future__ import annotations
import hashlib, json, re
from collections import Counter
from pathlib import Path
from typing import Any
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

PLACEHOLDER = re.compile(r"\[[A-ZÁÉÍÓÚÑ0-9 _.-]+\]")


def block_bookmark(requirement_id, block_id):
    digest = hashlib.sha256(f"{requirement_id}/{block_id}".encode()).hexdigest()
    return f"FO_{digest[:32]}"


def compare_blocks(data: dict, doc) -> list[dict]:
    assets = {asset["asset_id"]: asset for asset in data.get("assets", [])}
    numbers = {section.get("requirement_id"): section.get("number", 1)
               for section in data.get("document", {}).get("sections", [])}
    expected = []
    for section in data.get("document", {}).get("sections", []):
        if section.get("_spatial_blocks") or section.get("_table_blocks"):
            continue
        requirement_id = section.get("requirement_id")
        for block in section.get("blocks", []):
            kind = block["type"]
            asset = assets.get(block.get("asset_id"))
            if kind == "asset" and (not asset or not asset.get("include", True)):
                continue
            if kind == "support_list" and block.get("items") == []:
                continue
            if kind in {"requirement_text", "response_text", "support_list", "asset", "page_break"}:
                expected.append((block_bookmark(requirement_id, block["block_id"]), requirement_id, block))

    segments = {}
    active = None
    for node in doc._element.body:
        if node.tag == qn("w:bookmarkStart") and node.get(qn("w:name"), "").startswith("FO_"):
            active = node.get(qn("w:name"))
            if active in segments:
                return [{"group": "block_order", "value": "Marcador duplicado"}]
            segments[active] = (node.get(qn("w:id")), [])
        elif active and node.tag == qn("w:bookmarkEnd") and node.get(qn("w:id")) == segments[active][0]:
            active = None
        elif active:
            segments[active][1].append(node)

    missing = []
    if active or list(segments) != [name for name, _, _ in expected]:
        missing.append({"group": "block_order", "value": "Orden o numerales distintos del editor."})
    for name, requirement_id, block in expected:
        nodes = segments.get(name, (None, []))[1]
        kind = block["type"]
        values = block.get("items", []) if kind == "support_list" else [block.get("text", "")]
        paragraphs = [Paragraph(node, doc).text for node in nodes if node.tag == qn("w:p")]
        text = " ".join(" ".join(paragraphs).split())
        valid = all(" ".join(str(value).split()) in text for value in values)
        if kind == "requirement_text":
            valid = valid and bool(paragraphs) and paragraphs[0] == f"{numbers[requirement_id]}. Requerimiento de la autoridad"
        if kind == "asset":
            visual_ids = [
                *(tag.get("descr") for node in nodes for tag in node.xpath(".//wp:docPr")),
                *(tag.get(qn("w:val")) for node in nodes for tag in node.xpath(".//w:tblCaption")),
            ]
            valid = visual_ids == [block["asset_id"]]
        if kind == "page_break":
            valid = any(node.xpath('.//w:br[@w:type="page"]') for node in nodes)
        if not nodes or not valid:
            missing.append({"group": "block", "value": block["block_id"], "requirement_id": requirement_id})
    return missing

def canonical_expectations(data:dict[str,Any])->dict[str,Any]:
    responses=[]; supports=[]; assets=[]; requirements=[]
    for section in data.get('document',{}).get('sections',[]):
        for block in section.get('blocks',[]):
            kind=block.get('type')
            if kind=='requirement_text': requirements.append(block.get('text','').strip())
            elif kind=='response_text': responses.append(block.get('text','').strip())
            elif kind=='support_list': supports.extend(str(x).strip() for x in block.get('items',[]))
            elif kind=='asset': assets.append(block.get('asset_id'))
    return {'requirements':requirements,'responses':responses,'supports':supports,'assets':assets}

def docx_inventory(path:Path)->dict[str,Any]:
    doc=Document(path)
    paragraphs=[p.text.strip() for p in doc.paragraphs if p.text.strip()]
    table_cells=[c.text.strip() for t in doc.tables for row in t.rows for c in row.cells if c.text.strip()]
    text='\n'.join(paragraphs+table_cells)
    images=len(doc.inline_shapes)
    visual_tables = {}
    for table in doc.tables:
        for tag in table._tbl.tblPr.xpath('./w:tblCaption'):
            visual_tables.setdefault(tag.get(qn('w:val')), []).append(
                [[cell.text for cell in row.cells] for row in table.rows]
            )
    visual_ids = {
        'table': [asset_id for asset_id, tables in visual_tables.items() for _ in tables],
        'image': [shape._inline.docPr.get('descr') for shape in doc.inline_shapes],
    }
    page_breaks=sum(1 for p in doc.paragraphs for r in p.runs for br in r._r.xpath('.//w:br[@w:type="page"]'))
    return {'paragraphs':paragraphs,'table_cells':table_cells,'text':text,'tables':len(doc.tables),'images':images,'visual_ids':visual_ids,'visual_tables':visual_tables,'page_breaks':page_breaks,'placeholders':sorted(set(PLACEHOLDER.findall(text)))}

def compare_document_to_docx(data:dict[str,Any],path:Path)->dict[str,Any]:
    expected=canonical_expectations(data); actual=docx_inventory(path); missing=[]
    missing.extend(compare_blocks(data, Document(path)))
    def check(group,values):
        for value in values:
            if value and ' '.join(value.split()) not in ' '.join(actual['text'].split()): missing.append({'group':group,'value':value[:180]})
    check('requirement',expected['requirements']); check('response',expected['responses']); check('support',expected['supports'])
    selected = {a['asset_id']: a for a in data.get('assets', []) if a.get('include', True)}
    expected_ids = Counter()
    for asset_id in expected['assets']:
        asset = selected.get(asset_id)
        if asset:
            kind = 'table' if asset.get('type') == 'table' and asset.get('mode') == 'editable' and asset.get('rows') else 'image'
            expected_ids[kind, asset_id] += 1
    actual_ids = Counter((kind, asset_id) for kind, ids in actual['visual_ids'].items() for asset_id in ids)
    for kind, asset_id in (expected_ids - actual_ids).elements():
        missing.append({'group': 'asset', 'value': asset_id, 'type': kind})
    for kind, asset_id in expected_ids:
        if kind != 'table':
            continue
        rows = selected[asset_id]['rows']
        cols = max(map(len, rows))
        expected_cells = [row + [''] * (cols - len(row)) for row in rows]
        for cells in actual['visual_tables'].get(asset_id, []):
            if cells != expected_cells:
                missing.append({'group': 'table_cells', 'value': asset_id})
                break
    expected_visuals = sum(expected_ids.values())
    return {'valid':not missing,'missing':missing,'expected_visuals':expected_visuals,'docx':{k:v for k,v in actual.items() if k not in ('text','visual_tables')},'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def save_report(path:Path,result:dict[str,Any])->None:
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
