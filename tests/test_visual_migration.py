from docx import Document
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from processing_pipeline import ProcessingPipeline
from persistence import load_json_recover
from visual_assets import extract_visual_assets
from word_audit import compare_document_to_docx
from word_builder import build


def test_native_tables_and_small_image_reach_their_own_word_sections(tmp_path):
    source = tmp_path / "visuals.pdf"
    pdf = canvas.Canvas(str(source), pagesize=(612, 792))
    pdf.setFont("Helvetica", 10)
    for y, line in [
        (745, "Servicio de Administracion Tributaria"),
        (725, "Numero de oficio: 500-01-2026-123"),
        (705, "R.F.C. ABC010101XX0"),
        (680, "Se solicita lo siguiente:"),
        (650, "1. Proporcione los importes de cada operacion que se indica."),
        (490, "2) Aclare los conceptos de la relacion y revise la imagen adjunta."),
        (470, "a.Detalle del importe observado."),
    ]:
        pdf.drawString(50, y, line)

    ruled = [["Concepto", "Monto"], ["Ajuste", "$4,500.00"], ["Traslado", "$320.50"]]
    for x in (60, 165, 270):
        pdf.line(x, 530, x, 620)
    for y in (530, 560, 590, 620):
        pdf.line(60, y, 270, y)
    for index, row in enumerate(ruled):
        pdf.drawString(65, 602 - 30 * index, row[0])
        pdf.drawString(170, 602 - 30 * index, row[1])

    borderless = [["Clave", "Detalle"], ["A1", "Servicio externo"], ["B2", "Equipo nuevo"]]
    for index, row in enumerate(borderless):
        pdf.drawString(65, 450 - 18 * index, row[0])
        pdf.drawString(190, 450 - 18 * index, row[1])
    pdf.drawImage(ImageReader(Image.new("RGB", (96, 80), "navy")), 70, 260, width=48, height=40)
    pdf.setFillColorRGB(.2, .4, .8)
    pdf.circle(200, 280, 25, stroke=0, fill=1)
    pdf.save()

    result = ProcessingPipeline(tmp_path / "work").run("visual-test", source)
    session = tmp_path / "work" / result["session_id"]
    data = load_json_recover(session / "workspace.json")
    table, other_table, image, vector = data["assets"]
    assert table["rows"] == ruled
    assert other_table["rows"] == borderless
    assert "$4,500.00" not in data["points"][0]["text"]
    assert "Servicio externo" not in data["points"][1]["text"]
    assert image["type"] == vector["type"] == "image"
    assert [p["asset_ids"] for p in data["points"]] == [
        [table["asset_id"]], [other_table["asset_id"], image["asset_id"], vector["asset_id"]],
    ]

    output = session / "out.docx"
    build(data, output, session / "assets")
    doc = Document(output)
    matrices = [[[cell.text for cell in row.cells] for row in item.rows] for item in doc.tables]
    assert ruled in matrices and borderless in matrices
    assert len(doc.inline_shapes) == 2
    assert compare_document_to_docx(data, output)["valid"]

    # An ordinary Word table or an image with a different identity cannot cover a missing asset.
    doc.inline_shapes[0]._inline.docPr.set("descr", "unexpected-image")
    doc.save(output)
    missing = compare_document_to_docx(data, output)["missing"]
    assert {"group": "asset", "value": image["asset_id"], "type": "image"} in missing
    assert any(item.get("requirement_id") == "REQ-002" for item in missing)


def test_scan_layout_uses_original_pdf_crops_and_does_not_copy_full_page(tmp_path):
    source = tmp_path / "scan.pdf"
    pdf = canvas.Canvas(str(source), pagesize=(612, 792))
    pdf.drawImage(ImageReader(Image.new("RGB", (612, 792), "white")), 0, 0, 612, 792)
    pdf.save()
    points = [{"number": 1, "page_start": 1, "page_end": 1}]
    ocr = [{
        "page": 1, "layout_size": [1224, 1584],
        "tables": [{"bbox": [200, 300, 600, 500], "confidence": .95}],
        "regions": [{"type": "figure", "bbox": [220, 800, 640, 1100], "confidence": .92}],
    }]

    assets = extract_visual_assets(source, tmp_path / "assets", points, ocr)
    assert [(asset["type"], asset["mode"], asset["bbox"]) for asset in assets] == [
        ("table", "image", [100, 150, 300, 250]),
        ("image", "image", [110, 400, 320, 550]),
    ]
    assert points[0]["asset_ids"] == [asset["asset_id"] for asset in assets]
    assert all((tmp_path / "assets" / asset["file"]).is_file() for asset in assets)


def test_merged_table_is_exported_as_a_faithful_crop(tmp_path):
    source = tmp_path / "merged.pdf"
    pdf = canvas.Canvas(str(source), pagesize=(612, 792))
    pdf.rect(60, 540, 240, 90)
    for y in (570, 600):
        pdf.line(60, y, 300, y)
    pdf.line(180, 540, 180, 600)
    pdf.drawString(75, 610, "Encabezado combinado")
    pdf.drawString(75, 580, "Concepto")
    pdf.drawString(195, 580, "Importe")
    pdf.drawString(75, 550, "Servicio")
    pdf.drawString(195, 550, "1,200.00")
    pdf.save()

    points = [{
        "number": 1, "page_start": 1, "page_end": 1,
        "text": "Consulte el cuadro de importes de referencia.",
    }]
    assets = extract_visual_assets(source, tmp_path / "assets", points)
    assert [(asset["type"], asset["mode"]) for asset in assets] == [("table", "image")]
    data = {"points": points, "assets": assets}
    output = tmp_path / "merged.docx"
    build(data, output, tmp_path / "assets")
    assert len(Document(output).inline_shapes) == 1
    assert compare_document_to_docx(data, output)["valid"]
