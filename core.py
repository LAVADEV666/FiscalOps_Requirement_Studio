from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pdfplumber
from text_normalizer import FiscalOpsNormalizer, normalize_extracted_text
from ocr_engine import OCREngine
from paddle_ocr_engine.schema import empty_result
from visual_assets import detect_native_tables
from config import ocr_dpi_for_page
from boundary_analyzer import analyze_boundaries

LOGGER = logging.getLogger("fiscalops.extract")


class NoRequirementDetected(ValueError):
    pass

MAIN = re.compile(r"(?m)^\s*(\d{1,2})\s*(?:\.\s*[-–—]?|[-–—]|\))\s*(?=\S)")
ANCHORS = [re.compile(value, re.I | re.S) for value in (
    r"le\s+requiere\s+la\s+documentaci[oó]n\s+e\s+informaci[oó]n\s+adicional\s+que\s+m[aá]s\s+adelante\s+se\s+indica\s*:",
    r"le\s+requiere.*?(?:informaci[oó]n|documentaci[oó]n).*?(?:que\s+se\s+indica|siguiente)\s*:",
    r"proporcione\s+de\s+manera\s+digitalizada.*?(?:documentaci[oó]n|informaci[oó]n)\s*:",
    r"por\s+lo\s+anterior\s*,?\s*se\s+le\s+requiere",
    r"se\s+solicita\s+lo\s+siguiente\s*:",
    r"se\s+le\s+reitera\s+lo\s+siguiente\s*:",
    r"deber[aá]\s+aportar\s+lo\s+siguiente\s*:",
)]
ENDINGS = [re.compile(value, re.I) for value in (
    r"(?m)^\s*Por lo anterior y para estar en posibilidad de resolver",
    r"(?m)^\s*La información y documentación en respuesta",
    r"(?m)^\s*La citada información y/o documentación",
    r"(?m)^\s*Notifíquese\.",
    r"(?m)^\s*A\s+t\s+e\s+n\s+t\s+a\s+m\s+e\s+n\s+t\s+e",
)]
NOISE = [re.compile(value, re.I) for value in (
    r"^Administraci[oó]n General", r"^Administraci[oó]n Central",
    r"^Administraci[oó]n de Fiscalizaci[oó]n", r"^Administraci[oó]n Desconcentrada",
    r"^Subadministraci[oó]n", r"^N[uú]mero de oficio", r"^Expediente",
    r"^R\.F\.C\.\s*", r"^N[uú]mero de referencia", r"^RDGR/PJRG/JAS",
    r"^Av\.", r"Marca SAT", r"sat\.gob\.mx", r"^\d+\s*/\s*\d+$",
)]
ACT_TERMS = ("número de oficio", "numero de oficio", "expediente", "r.f.c.", "rfc", "servicio de administración tributaria", "servicio de administracion tributaria")
REQUEST_TERMS = ("se solicita", "le requiere", "requerimiento", "deberá aportar", "proporcione", "información adicional", "documentación adicional")


def clean(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value.replace("\u00ad", "").replace("\xa0", " ")).strip()


def native(page) -> bool:
    words = page.extract_words(x_tolerance=2, y_tolerance=3)
    readable = [item["text"] for item in words if "\ufffd" not in item["text"] and "(cid:" not in item["text"]]
    return len(readable) >= 18 and len(readable) >= len(words) * .8 and sum(map(len, readable)) >= 100


def ocr(page, engine: OCREngine | None = None) -> dict[str, Any]:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        dpi = ocr_dpi_for_page(page.width, page.height)
        image_path = Path(td) / "page.png"
        page.to_image(resolution=dpi).original.convert("RGB").save(image_path)
        service = engine or OCREngine(Path(td)/'cache')
        return service.run(image_path)


def _one(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.I)
    return clean(match.group(1)) if match else ""


def _ocr_rfc(text: str) -> str:
    """Read an RFC even when OCR inserts spaces between character groups."""
    for line in str(text or "").splitlines():
        if not re.search(r"\bR\s*\.?\s*F\s*\.?\s*C\s*\.?\b|\bRFC\b", line, re.I):
            continue
        tail = re.sub(r"^.*?R\s*\.?\s*F\s*\.?\s*C\s*\.?\s*[:\-]?", "", line, flags=re.I)
        compact = re.sub(r"[^A-Z0-9Ñ&]", "", tail.upper())
        for length in (12, 13):
            for start in range(max(1, len(compact) - length + 1)):
                candidate = compact[start:start + length]
                repaired, _, valid = FiscalOpsNormalizer.repair_rfc(candidate)
                if valid:
                    return repaired
                if FiscalOpsNormalizer.RFC_PATTERN.fullmatch(candidate):
                    return candidate
    return ""


def _field(name: str, value: str, confidence: float, source: str, message: str = "") -> dict[str, Any]:
    return {"name": name, "value": value or "[REVISAR MANUALMENTE]", "confidence": confidence if value else .25, "valid": bool(value), "source": source, "message": message or "Editable y sujeto a revisión."}


def metadata(text: str) -> dict[str, Any]:
    detected_rfc = _ocr_rfc(text)
    values = {
        "rfc": _field("RFC", detected_rfc, .99, "encabezado"),
        "office": _field("Número de oficio", _one(text, r"N[uú]mero\s+de\s+oficio\s*:?\s*([A-Z0-9.-]*\d{4}\s*-\s*\d+)"), .98, "encabezado"),
        "reference": _field("Número de referencia", _one(text, r"N[uú]mero de referencia\s*:?[ ]*([A-Z0-9-]+)"), .98, "encabezado"),
        "expedient": _field("Expediente", _one(text, r"Expediente\s*:?[ ]*([^\n]+)"), .96, "encabezado"),
        "taxpayer_name": _field("Razón social", _one(text, r"C\.?\s*Representante Legal de\s*:\s*\n?([^\n]+)"), .92, "primera página"),
        "date": _field("Fecha del oficio", _one(text, r"Ciudad de México,?\s+a\s+(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚáéíóú]+\s+de\s+\d{4})"), .95, "primera página"),
        "deadline": _field("Plazo concedido", _one(text, r"plazo máximo de\s+(\d+\s+d[ií]as\s+h[aá]biles)"), .94, "cierre"),
        "period": _field("Periodo", _one(text, r"correspondiente al periodo de\s+([^\.\n]+)"), .90, "cuerpo"),
        "amount": _field("Monto", _one(text, r"(?:en cantidad de|importe)\s*:?\s*(\$\s*[\d,]+\.\d{1,2})"), .95, "cuerpo"),
    }
    values.update({
        "control": _field("Número de control o seguimiento", _one(text, r"número de control\s+([A-Z0-9-]+)"), .90, "cuerpo"),
        "notification_date": _field("Fecha de notificación", _one(text, r"notificad[oa]\s+el\s+(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚáéíóú]+(?:\s+de\s+\d{4})?)"), .78, "antecedentes"),
        "tax": _field("Impuesto", _one(text, r"por concepto de\s+([^,\n]{4,100})"), .88, "cuerpo"),
        "request_type": _field("Tipo de acto", _one(text, r"Asunto\s*:\s*([^\n]+)"), .88, "primera página"),
        "authority": _field("Autoridad emisora", _one(text, r"(Administraci[oó]n (?:Central|Desconcentrada)[^\n]{5,140})"), .85, "encabezado"),
        "administrative_unit": _field("Unidad administrativa", _one(text, r"(Subadministraci[oó]n[^\n]{5,120})"), .85, "encabezado"),
        "legal_representative": {"name":"Representante legal","value":"[NO EXTRAER AUTOMÁTICAMENTE]","confidence":1.0,"valid":True,"source":"privacidad","message":"Dato personal excluido de la extracción automática."},
    })
    return {"status": "ok" if values["rfc"]["valid"] and values["office"]["valid"] else "review", "fields": values, "policy": "Los datos se revisan y corrigen en pantalla."}


def coherent(matches):
    best = []
    for index, first in enumerate(matches):
        if int(first.group(1)) != 1:
            continue
        current, expected = [first], 2
        for item in matches[index + 1:]:
            number = int(item.group(1))
            if number == expected:
                current.append(item); expected += 1
            elif number == 1 and len(current) > 1:
                break
            elif number > expected + 5:
                break
        if len(current) > len(best):
            best = current
    return best


def extract(path: Path, ocr_engine: OCREngine | None = None,
            native_tables: dict[int, list] | None = None, *, recover_ocr: bool = False,
            allow_manual: bool = False, native_page_numbers: set[int] | None = None,
            boundary_client: Any | None = None) -> dict[str, Any]:
    raw_pages, parse_pages, native_count, ocr_count, ocr_pages = [], [], 0, 0, []
    ocr_ready = None
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            raise ValueError("El PDF no contiene páginas.")
        for page_number, page in enumerate(pdf.pages, 1):
            if native(page) or page_number in (native_page_numbers or set()):
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""; native_count += 1
                if native_tables is not None:
                    tables = list(detect_native_tables(page, page.extract_words()))
                    native_tables[page_number] = tables
                    if tables:
                        def outside_tables(char):
                            if char.get("object_type") != "char":
                                return True
                            x = (char["x0"] + char["x1"]) / 2
                            y = (char["top"] + char["bottom"]) / 2
                            return not any(box[0] <= x <= box[2] and box[1] <= y <= box[3]
                                           for box, _, _ in tables)
                        raw_pages.append(text)
                        parse_pages.append(page.filter(outside_tables).extract_text(x_tolerance=2, y_tolerance=3) or "")
                        continue
            else:
                try:
                    if recover_ocr and ocr_engine is not None:
                        if ocr_ready is None:
                            ocr_ready = ocr_engine.is_usable()
                        if not ocr_ready:
                            raise RuntimeError("PaddleOCR local no disponible. Ejecuta INSTALAR_OCR.bat.")
                    result = ocr(page, ocr_engine)
                except (RuntimeError, ValueError, OSError) as error:
                    if not recover_ocr:
                        raise
                    LOGGER.warning("La lectura automática de la página %s falló (%s).", page_number, type(error).__name__)
                    message = "PaddleOCR local no disponible. Ejecuta INSTALAR_OCR.bat." if ocr_ready is False else "No se pudo leer esta página automáticamente."
                    result = empty_result(f"page-{page_number}.png", message)
                result["page"] = page_number
                text = result.get("text", "")
                ocr_pages.append(result)
                ocr_count += 1
            raw_pages.append(text)
            parse_pages.append(text)
    pages = ["\n".join(clean(line) for line in text.splitlines() if clean(line) and not any(pattern.search(clean(line)) for pattern in NOISE)) for text in parse_pages]
    full, raw_full = "\n\n".join(pages), "\n".join(raw_pages)
    anchors = [match for pattern in ANCHORS for match in pattern.finditer(full)]
    candidates = []
    for anchor in anchors:
        sequence = coherent(list(MAIN.finditer(full, anchor.end())))
        if sequence:
            candidates.append((len(sequence), -anchor.start(), anchor, sequence))
    if candidates:
        _, _, anchor, markers = max(candidates, key=lambda item: (item[0], item[1]))
        strategy = "anchored_sequence"
    else:
        anchor, markers = None, coherent(list(MAIN.finditer(full)))
        strategy = "global_sequence"
    folded = raw_full.lower()
    act_hits = [term for term in ACT_TERMS if term in folded]
    request_hits = [term for term in REQUEST_TERMS if term in folded]
    points = []
    boundaries = analyze_boundaries(pages, boundary_client)
    if boundaries["segments"]:
        for segment in boundaries["segments"]:
            raw_point = segment["text"].strip()
            points.append({
                "number": int(segment["number"]),
                "text": normalize_extracted_text(raw_point),
                "raw_text": raw_point,
                "page_start": segment["page_start"],
                "page_end": segment["page_end"],
                "boundary": {
                    "version": boundaries["version"],
                    "method": segment["method"],
                    "confidence": segment["confidence"],
                    "review_required": segment["review_required"],
                    "start_line_id": segment["start_line_id"],
                    "end_line_id": segment["end_line_id"],
                    "reason": segment.get("reason", ""),
                },
            })
        first = boundaries["segments"][0]["start_index"]
        last = boundaries["segments"][-1]["end_index"]
        records = boundaries["records"]
        introduction = "\n".join(item["text"] for item in records[:first]).strip() or "[INICIO INFERIDO POR ANCLAS DE SOLICITUD]"
        general_instructions = "\n".join(item["text"] for item in records[last + 1:]).strip()
        strategy = boundaries["method"]
    elif markers:
        start = markers[0].start()
        ending_matches = [match for pattern in ENDINGS if (match := pattern.search(full, start))]
        finish = min((match.start() for match in ending_matches), default=len(full))
        markers = [match for match in markers if match.start() < finish]
        def page_at(offset):
            cursor = 0
            for page_number, text in enumerate(pages, 1):
                if offset <= cursor + len(text): return page_number
                cursor += len(text) + 2
            return len(pages)
        for index, marker in enumerate(markers):
            stop = markers[index + 1].start() if index + 1 < len(markers) else finish
            raw_point = full[marker.end():stop].strip()
            points.append({"number": int(marker.group(1)), "text": normalize_extracted_text(raw_point), "raw_text": raw_point, "page_start": page_at(marker.start()), "page_end": page_at(max(marker.start(), stop - 1))})
        introduction = clean(full[anchor.start():markers[0].start()]) if anchor else "[INICIO INFERIDO POR SECUENCIA PRINCIPAL]"
        general_instructions = full[finish:].strip()
    elif len(act_hits) >= 2 and request_hits:
        start = max((anchor.end() for anchor in anchors), default=0)
        ending_matches = [match for pattern in ENDINGS if (match := pattern.search(full, start))]
        finish = min((match.start() for match in ending_matches), default=len(full))
        block = normalize_extracted_text(full[start:finish].strip())
        points = [{"number": 1, "text": block, "raw_text": block, "page_start": 1, "page_end": len(pages)}]
        introduction = "[ACTO ADMINISTRATIVO SIN NUMERACIÓN PRINCIPAL: BLOQUE ÚNICO GENERADO]"
        general_instructions = full[finish:].strip()
        strategy = "single_block_fallback"
    elif allow_manual or (recover_ocr and ocr_pages):
        introduction = general_instructions = ""
        strategy = "manual_ocr"
    else:
        raise NoRequirementDetected("El PDF es legible, pero la lectura automática no encontró un requerimiento fiscal.")
    classification = {"is_administrative_act": len(act_hits) >= 2, "is_requirement": bool(request_hits), "confidence": min(100, len(act_hits) * 15 + len(request_hits) * 10 + len(points) * 8), "strategy": strategy, "main_points": [point["number"] for point in points], "signals": {"act": act_hits, "request": request_hits}}
    detected_numerals = [
        {**item, "page": page_result["page"]}
        for page_result in ocr_pages
        for item in page_result.get("numerals", [])
    ]
    return {"source_file": path.name, "document_type": "native" if not ocr_count else ("scanned" if not native_count else "mixed"), "pages": len(pages), "native_pages": native_count, "ocr_pages": ocr_count, "introduction": introduction, "points": points, "metadata_validation": metadata(raw_full), "general_instructions": general_instructions, "warnings": [], "classification": classification, "diagnostics": {"anchors_found": len(anchors), "main_point_count": len(points), "strategy": strategy, "boundary_model": {"model": boundaries.get("model"), "status": boundaries.get("model_status"), "method": boundaries.get("method")}}, "ocr_diagnostics": {"pages": ocr_pages, "review_required": sum(bool(x.get("requires_review")) for x in ocr_pages)}, "detected_numerals": detected_numerals}
