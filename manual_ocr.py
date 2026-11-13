from __future__ import annotations

from contextlib import nullcontext
from math import ceil, floor, sqrt
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import uuid4

import fitz
from PIL import Image
from pydantic import BaseModel, Field, FiniteFloat

from audit_engine import audit_event, validate_integrity
from compliance_engine import create_matrix, ensure_matrix
from document_model import build_document, ensure_document, update_document

Coordinate = Annotated[FiniteFloat, Field(ge=0, le=1)]
MAX_ZONES = 8
MAX_TEXT = 100_000


class Region(BaseModel):
    page: Annotated[int, Field(ge=1)]
    rect: tuple[Coordinate, Coordinate, Coordinate, Coordinate]

    def bounds(self) -> tuple[float, float, float, float]:
        start_x, start_y, end_x, end_y = self.rect
        x0, x1 = sorted((start_x, end_x))
        y0, y1 = sorted((start_y, end_y))
        if min(x1 - x0, y1 - y0) < .002:
            raise ValueError("Marca un rectángulo más grande en el visor.")
        return x0, y0, x1, y1


def validate_regions(folder: Path, regions: list[Region], pages: int) -> None:
    for region in regions:
        region.bounds()
        if region.page > pages or not (folder / "pages" / f"page-{region.page}.png").is_file():
            raise ValueError(f"La página {region.page} no está disponible en el visor.")


def native_text(page: fitz.Page, clip: fitz.Rect) -> str:
    lines = {}
    for x0, y0, x1, y1, text, block, line, _ in page.get_text("words", sort=True):
        center = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2) * page.rotation_matrix
        if clip.contains(center):
            lines.setdefault((block, line), []).append(text)
    text = "\n".join(" ".join(words) for words in lines.values())
    if "\ufffd" in text or "(cid:" in text or not any(char.isalnum() for char in text):
        return ""
    return text


def render_region(page: fitz.Page | None, image_path: Path, bounds: tuple, output: Path, rotation: int) -> None:
    x0, y0, x1, y1 = bounds
    if page is not None:
        rect = page.rect
        clip = fitz.Rect(x0 * rect.width, y0 * rect.height, x1 * rect.width, y1 * rect.height)
        scale = min(400 / 72, sqrt(5_000_000 / clip.get_area()), 3200 / max(clip.width, clip.height))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    else:
        with Image.open(image_path) as source:
            width, height = source.size
            image = source.crop((floor(x0 * width), floor(y0 * height), ceil(x1 * width), ceil(y1 * height))).convert("RGB")
        scale = min(2, sqrt(5_000_000 / (image.width * image.height)), 3200 / max(image.size))
        if scale != 1:
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
    if rotation:
        image = image.rotate(-rotation, expand=True, fillcolor="white")
    image.save(output)


def read_regions(folder: Path, regions: list[Region], engine, *, force_ocr=False, rotation=0) -> list[dict]:
    pdf = folder / "source.pdf"
    results = []
    with (fitz.open(pdf) if pdf.is_file() else nullcontext()) as doc, TemporaryDirectory(prefix="fiscalops-ocr-") as temp:
        for number, region in sorted(enumerate(regions, 1), key=lambda item: item[1].page):
            bounds = region.bounds()
            page = doc[region.page - 1] if doc is not None and region.page <= len(doc) else None
            result = {"zone": number, "page": region.page, "rect": bounds, "method": "paddleocr", "text": "", "confidence": None}
            if page is not None and not force_ocr and not rotation:
                x0, y0, x1, y1 = bounds
                rect = page.rect
                text = native_text(page, fitz.Rect(x0 * rect.width, y0 * rect.height, x1 * rect.width, y1 * rect.height))
                if text:
                    results.append({**result, "method": "native", "text": text[:MAX_TEXT]})
                    continue
            try:
                crop = Path(temp) / "region.png"
                render_region(page, folder / "pages" / f"page-{region.page}.png", bounds, crop, rotation)
                reading = engine.read_region(crop)
                result.update(text=reading["text"][:MAX_TEXT], confidence=reading["confidence"])
                if not result["text"]:
                    result["warning"] = "No se encontró texto. Ajusta el recuadro o captura el texto en la revisión."
            except RuntimeError as error:
                result["warning"] = str(error) if "INSTALAR_OCR.bat" in str(error) else "Falló la lectura de esta zona. Puedes ajustar el recuadro o transcribirla."
            except (OSError, ValueError):
                result["warning"] = "No se pudo leer el recorte de esta página."
            results.append(result)
    return results


def apply_reading(data: dict, regions: list[Region], requirement_id: str | None, text: str) -> str:
    text = text.strip()
    if not text or any(ord(char) < 32 and char not in "\t\n\r" for char in text):
        raise ValueError("Escribe el texto final del numeral antes de aplicar la lectura.")
    document = ensure_document(data)
    points = data.setdefault("points", [])
    pages = [region.page for region in regions]
    new = requirement_id is None
    if new:
        number = max((int(point["number"]) for point in points), default=0) + 1
        requirement_id = f"REQ-{number:03d}"
        point = {"requirement_id": requirement_id, "number": number, "text": text, "original_text": text,
                 "page_start": min(pages), "page_end": max(pages), "version": 0, "include": True, "fragment_ids": []}
        points.append(point)
        document["sections"].extend(build_document({"points": [point]})["sections"])
        before = ""
    else:
        point = next((p for p in points if p.get("requirement_id") == requirement_id), None)
        if point is None:
            raise ValueError("El numeral elegido ya no existe.")
        before = point["text"]
        point["page_start"] = min(point.get("page_start") or min(pages), *pages)
        point["page_end"] = max(point.get("page_end") or max(pages), *pages)

    fragments = data.setdefault("fragments", [])
    identifiers = list(point.get("fragment_ids") or [])
    manual = {(fragment["page"], tuple(fragment["bbox"][key] for key in ("x0", "y0", "x1", "y1")))
              for fragment in fragments if fragment["fragment_id"] in identifiers and fragment.get("method") == "manual_ocr"}
    for region in regions:
        bounds = region.bounds()
        if (region.page, bounds) in manual:
            continue
        manual.add((region.page, bounds))
        fragment_id = f"FRG-OCR-{uuid4().hex}"
        identifiers.append(fragment_id)
        fragments.append({"fragment_id": fragment_id, "requirement_id": requirement_id, "type": "requirement",
                          "page": region.page, "bbox": dict(zip(("x0", "y0", "x1", "y1"), bounds)),
                          "page_size": {"width": 1, "height": 1}, "method": "manual_ocr",
                          "confidence": 1.0, "status": "reviewed"})
    section = next(s for s in document["sections"] if s["requirement_id"] == requirement_id)
    block = next(b for b in section["blocks"] if b["type"] == "requirement_text")
    if block["text"] != text:
        block.pop("paragraphs", None)
    block.update(text=text, source_fragment_ids=identifiers, version=block.get("version", 0) + 1)
    point.update(text=text, fragment_ids=identifiers, status="review", version=point.get("version", 0) + 1)
    data["document_validation"] = update_document(data, document)
    if new and not any(row["requirement_id"] == requirement_id for row in ensure_matrix(data)["rows"]):
        data["compliance_matrix"]["rows"].extend(create_matrix({"points": [point]})["rows"])
        ensure_matrix(data)
    data["validation"] = validate_integrity(data)
    data.setdefault("audit_log", []).append(audit_event("MANUAL_OCR_APPLIED", requirement_id, identifiers[-1], before, text))
    return requirement_id
