"""
processing_pipeline.py — Enrutador inteligente con triage PyMuPDF.

Evalúa cada página del PDF de entrada para decidir la estrategia de extracción:
  - Páginas con texto nativo (fitz)   → extracción directa + coordenadas.
  - Páginas escaneadas (imágenes)     → envío al motor OCR (PaddleOCR).

El pipeline mantiene compatibilidad con el flujo existente (core.extract,
FiscalOpsNormalizer, audit_engine, etc.) añadiendo metadata de triage.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from core import extract
from text_normalizer import FiscalOpsNormalizer
from audit_engine import build_fragments, render_pages, validate_integrity, audit_event
from visual_assets import extract_visual_assets
from document_model import ensure_document, validate_document
from compliance_engine import ensure_matrix
from persistence import atomic_json
from ocr_engine import OCREngine
from document_inspector import inspect_pdf
from ocr_decision_engine import decide_document
from document_reconstruction import reconstruct_document
from cross_validation import validate_cross_sources
from fiscal_interpreter import interpret_document
from mixed_region_ocr import run_mixed_region_ocr
from ollama_provider import OllamaClient

LOGGER = logging.getLogger("fiscalops.pipeline")

# Umbral de palabras mínimo para considerar texto nativo (consistente con core.native()).
MIN_WORDS = 18
# Mínimo absoluto de caracteres para ignorar páginas casi vacías.
MIN_TEXT_CHARS = 100


# ==============================================================================
# Triage PyMuPDF
# ==============================================================================

def triage_page(page: fitz.Page) -> dict[str, Any]:
    """
    Evalúa una sola página para determinar si es texto nativo o escaneo.

    Criterios:
      1. Extrae todas las palabras con fitz (coordenadas + texto).
      2. Calcula la proporción de texto vs. área de página.
      3. Si el texto supera NATIVE_TEXT_THRESHOLD y hay >MIN_TEXT_CHARS → native.
      4. Si la página tiene imágenes pero poco texto → scan.

    Retorna:
        {
            "strategy": "native" | "scan" | "mixed",
            "text_length": int,
            "word_count": int,
            "image_count": int,
            "text_ratio": float,
            "blocks": list[dict]   # solo en modo native/mixed
        }
    """
    try:
        # Ancho y alto de la página en puntos PDF (1 pt ≈ 1/72 pulg)
        rect = page.rect
        page_area = rect.width * rect.height

        # Extraer palabras con sus bounding boxes
        words = page.get_text("words")  # lista de (x0, y0, x1, y1, word, block_no, line_no, word_no)
        text_length = sum(len(w[4]) for w in words)
        word_count = len(words)

        # Contar imágenes en la página
        image_list = page.get_images(full=True)
        image_count = len(image_list)

        # Estimar ratio de texto: texto_chars / (ancho_página * líneas_estimadas)
        if words:
            max_y = max(w[3] for w in words)
            min_y = min(w[1] for w in words)
            text_height = max(max_y - min_y, 1)
            text_width = max(w[2] for w in words) - min(w[0] for w in words)
            text_area_est = text_width * text_height
            text_ratio = text_length / max(page_area, 1)
        else:
            text_ratio = 0.0
            text_area_est = 0

        # Construir bloques de texto estructurados (solo si hay texto significativo)
        blocks: list[dict[str, Any]] = []
        if word_count > 0:
            # Agrupar por bloque (block_no) para preservar estructura
            by_block: dict[int, list[dict[str, Any]]] = {}
            for w in words:
                x0, y0, x1, y1, word_text, block_no, line_no, word_no = w
                bn = int(block_no)
                entry = {
                    "text": word_text,
                    "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                    "block_no": bn,
                    "line_no": int(line_no),
                    "word_no": int(word_no),
                }
                by_block.setdefault(bn, []).append(entry)
            for bn in sorted(by_block):
                entries = by_block[bn]
                if not entries:
                    continue
                xs = [e["bbox"][0] for e in entries]
                ys = [e["bbox"][1] for e in entries]
                xe = [e["bbox"][2] for e in entries]
                ye = [e["bbox"][3] for e in entries]
                full_text = " ".join(e["text"] for e in entries)
                blocks.append({
                    "block_no": bn,
                    "text": full_text.strip(),
                    "bbox": [
                        round(min(xs), 2), round(min(ys), 2),
                        round(max(xe), 2), round(max(ye), 2),
                    ],
                    "word_count": len(entries),
                })

        # Decisión de estrategia: compatible con core.native() para保持一致性
        has_significant_text = word_count >= MIN_WORDS and text_length >= MIN_TEXT_CHARS
        is_scan = image_count > 0 and not has_significant_text
        is_mixed = has_significant_text and image_count > 0

        if is_scan:
            strategy = "scan"
        elif is_mixed:
            strategy = "mixed"
        else:
            strategy = "native" if has_significant_text else "scan"

        return {
            "strategy": strategy,
            "text_length": text_length,
            "word_count": word_count,
            "image_count": image_count,
            "text_ratio": round(text_ratio, 4),
            "blocks": blocks,
            "is_native": strategy in ("native", "mixed"),
            "is_scan": strategy in ("scan",),
        }

    except Exception as exc:
        LOGGER.warning("Error en triage de página: %s", exc)
        return {
            "strategy": "scan",
            "text_length": 0,
            "word_count": 0,
            "image_count": 0,
            "text_ratio": 0.0,
            "blocks": [],
            "is_native": False,
            "is_scan": True,
            "error": str(exc),
        }


def triage_pdf(pdf_path: Path) -> dict[str, Any]:
    """
    Triage integral de un PDF: evalúa todas las páginas.

    Retorna estadísticas globales y por-página.
    """
    try:
        doc = fitz.open(str(pdf_path))
    except fitz.EmptyFileError:
        raise ValueError("El archivo PDF está vacío o corrupto.")
    except Exception as exc:
        raise ValueError(f"No se pudo abrir el PDF: {exc}")

    page_results: list[dict[str, Any]] = []
    native_count = 0
    scan_count = 0
    mixed_count = 0
    total_text_chars = 0
    total_words = 0

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            result = triage_page(page)
            result["page_number"] = page_num + 1
            page_results.append(result)

            if result["is_native"]:
                native_count += 1
            if result["is_scan"]:
                scan_count += 1
            if result.get("strategy") == "mixed":
                mixed_count += 1

            total_text_chars += result["text_length"]
            total_words += result["word_count"]
    finally:
        doc.close()

    total_pages = len(page_results)
    native_ratio = native_count / max(total_pages, 1)

    # Estrategia global
    if native_ratio >= 0.8:
        global_strategy = "native_dominant"
    elif native_ratio <= 0.2:
        global_strategy = "scan_dominant"
    else:
        global_strategy = "mixed"

    return {
        "total_pages": total_pages,
        "native_pages": native_count,
        "scan_pages": scan_count,
        "mixed_pages": mixed_count,
        "native_ratio": round(native_ratio, 4),
        "global_strategy": global_strategy,
        "total_text_chars": total_text_chars,
        "total_words": total_words,
        "pages": page_results,
    }


# ==============================================================================
# Pipeline principal
# ==============================================================================

class ProcessingPipeline:
    """
    Pipeline de procesamiento de requerimientos fiscales del SAT / Tesorería CDMX.

    Integra triage PyMuPDF con el motor de extracción existente (core.extract)
    y añade metadatos de página para trazabilidad.
    """

    def __init__(self, work: Path, max_pages: int = 500, *, ocr_service: OCREngine | None = None, ollama_client: OllamaClient | None = None) -> None:
        self.work = Path(work)
        self.max_pages = max_pages
        self.work.mkdir(parents=True, exist_ok=True)
        self._ocr_service = ocr_service
        self._ollama_client = ollama_client

    @property
    def ocr_service(self) -> OCREngine:
        """Lazy init: el motor OCR se crea solo cuando se requiere, evitando
        directorios residuales en sesiones que fallan antes de terminar."""
        if self._ocr_service is None:
            self._ocr_service = OCREngine(self.work / "ocr_cache")
        return self._ocr_service

    def run(self, task_id: str, input_pdf: Path, progress: Any = None, *,
            recover_ocr: bool = False, allow_manual: bool = False) -> dict[str, Any]:
        """
        Ejecuta el pipeline completo sobre un PDF de entrada.

        Parámetros:
            task_id:    Identificador único de la tarea.
            input_pdf:  Ruta al PDF de entrada.
            progress:   Callback opcional (stage, pct, msg) para UI.

        Retorna:
            Dict con session_id, job_id, puntos detectados, páginas, tipo_doc.
        """
        tick = progress or (lambda stage, pct, msg="": None)
        started = time.perf_counter()
        sid = uuid.uuid4().hex
        d = self.work / sid
        d.mkdir(mode=0o700)
        pdf = d / "source.pdf"

        try:
            # ── Paso 1: Validación básica ──────────────────────────────────
            tick("validating", 5, "Validando PDF")
            try:
                raw_bytes = input_pdf.read_bytes()
            except FileNotFoundError:
                raise ValueError(f"Archivo no encontrado: {input_pdf}")
            except PermissionError:
                raise ValueError(f"Permiso denegado para leer: {input_pdf}")

            if raw_bytes[:5] != b"%PDF-":
                raise ValueError("PDF inválido: el archivo no comienza con la cabecera %PDF.")

            shutil.copy2(input_pdf, pdf)

            # ── Paso 2: Triage con PyMuPDF ────────────────────────────────
            tick("triage", 12, "Evaluando páginas con PyMuPDF")
            triage = triage_pdf(pdf)
            if triage["total_pages"] > self.max_pages:
                raise ValueError(f"El PDF excede {self.max_pages} páginas.")
            LOGGER.info(
                "Triage: %d págs totales | nativas=%d scanned=%d mixed=%d ratio=%.1f%%",
                triage["total_pages"], triage["native_pages"],
                triage["scan_pages"], triage["mixed_pages"],
                triage["native_ratio"] * 100,
            )

            # Guardar resultado del triage
            (d / "triage.json").write_text(
                json.dumps(triage, ensure_ascii=False, indent=2), encoding="utf-8",
            )

            # ── Paso 2b: inspección completa y decisión OCR ─────────────
            tick("inspection", 15, "Inspeccionando todas las páginas")
            inspection = inspect_pdf(pdf)
            decisions = decide_document(inspection)
            (d / "document_inspection.json").write_text(
                json.dumps(inspection, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            (d / "ocr_decisions.json").write_text(
                json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8",
            )

            # ── Paso 3: Verificar disponibilidad de OCR para páginas escaneadas ──
            if not recover_ocr and triage["scan_pages"] > 0 and not self.ocr_service.is_usable():
                raise ValueError(
                    "El PDF contiene páginas escaneadas pero no hay ningún motor OCR "
                    "disponible. Ejecute INSTALAR_OCR.bat para instalar PaddleOCR y "
                    "descargar sus modelos locales antes de procesar documentos."
                )

            # ── Paso 4: Extracción principal (core.extract con soporte triage) ──
            tick("extracting", 18, "Extrayendo texto y OCR")
            native_tables = {}
            native_page_numbers = {
                int(page.get("page", 0)) for page in inspection.get("pages", [])
                if page.get("page_type") in {"DIGITAL_TEXT", "MIXED_CONTENT"} and page.get("has_native_text")
            }
            data = FiscalOpsNormalizer.normalize_workspace(extract(
                pdf, self.ocr_service, native_tables, recover_ocr=recover_ocr,
                allow_manual=allow_manual, native_page_numbers=native_page_numbers,
                boundary_client=self._ollama_client))
            data["triage"] = triage
            data["document_inspection"] = inspection
            data["ocr_decisions"] = decisions

            # Mixed pages retain native text as the canonical reading.  OCR is
            # limited to embedded visual regions and stored as supplemental
            # evidence, never concatenated blindly into the page text.
            tick("mixed_regions", 24, "Leyendo regiones visuales necesarias")
            has_mixed_pages = any(page.get("page_type") == "MIXED_CONTENT" for page in inspection.get("pages", []))
            mixed_regions = run_mixed_region_ocr(
                pdf, d / "ocr_regions", inspection, self.ocr_service,
                enabled=recover_ocr,
            ) if has_mixed_pages else {"regions": [], "summary": {"pages": 0, "regions": 0, "processed": 0, "review_required": 0, "skipped": 0}}
            data.setdefault("ocr_diagnostics", {})["mixed_regions"] = mixed_regions.get("regions", [])
            data["ocr_diagnostics"]["mixed_region_summary"] = mixed_regions.get("summary", {})

            # ── Paso 4b: reconstrucción canónica con trazabilidad ─────────
            tick("reconstructing", 30, "Reconstruyendo el documento por página")
            reconstruction = reconstruct_document(pdf, inspection, data)
            data["reconstruction"] = reconstruction

            # ── Paso 5: Segmentación de numerales ─────────────────────────
            tick("segmenting", 36, "Delimitando numerales")
            fragments = build_fragments(pdf, data["points"], data.get("ocr_diagnostics", {}).get("pages", []))
            for point in data["points"]:
                rid = f"REQ-{int(point['number']):03d}"
                point["requirement_id"] = rid
                point["fragment_ids"] = [
                    x["fragment_id"] for x in fragments if x["requirement_id"] == rid
                ]
                point.update(
                    status="detected", version=1,
                    original_text=point["text"], include=True,
                )
            data["fragments"] = fragments

            # ── Paso 6: Activos visuales ──────────────────────────────────
            tick("visuals", 52, "Extrayendo tablas e imágenes")
            data["assets"] = extract_visual_assets(
                pdf, d / "assets", data["points"], data.get("ocr_diagnostics", {}).get("pages", []), native_tables,
            )

            # ── Paso 7: Modelo documental ─────────────────────────────────
            tick("document", 66, "Creando modelo documental")
            ensure_document(data)
            data["document_validation"] = validate_document(data["document"], data)
            ensure_matrix(data)

            # ── Paso 7b: validación cruzada e interpretación posterior ─────
            tick("cross_validation", 72, "Validando fuentes y campos críticos")
            cross_validation = validate_cross_sources(reconstruction, data)
            data["cross_validation"] = cross_validation
            data["fiscal_interpretation"] = interpret_document(data, reconstruction, cross_validation, client=self._ollama_client)
            data["processing_metrics"] = {
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "pages": inspection["total_pages"],
                "pages_inspected": inspection["inspected_pages"],
                "completed": True,
            }

            # ── Paso 8: Renderizado de páginas (imágenes) ─────────────────
            tick("rendering", 80, "Renderizando páginas")
            data["pages_manifest"] = render_pages(pdf, d / "pages")

            # ── Paso 8: Validación de integridad ──────────────────────────
            tick("validating_output", 92, "Validando integridad")
            data["validation"] = validate_integrity(data)
            data["audit_log"] = [audit_event("DOCUMENT_PROCESSED")]
            data["processing_task_id"] = task_id

            # ── Paso 9: Persistencia ──────────────────────────────────────
            atomic_json(d / "workspace.json", data, backup=False)
            (d / "audit.jsonl").write_text(
                json.dumps(data["audit_log"][0], ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            tick("finalizing", 98, "Preparando expediente")
            return {
                "session_id": sid,
                "job_id": sid,
                "points": len(data.get("points", [])),
                "pages": data.get("pages", 0),
                "document_type": data.get("document_type"),
                "triage": {
                    "global_strategy": triage["global_strategy"],
                    "native_pages": triage["native_pages"],
                    "scan_pages": triage["scan_pages"],
                },
                "inspection": {
                    "total_pages": inspection["total_pages"],
                    "classification_counts": inspection["classification_counts"],
                    "coverage": inspection["coverage"],
                },
                "ocr_decisions": decisions["summary"],
                "processing_metrics": data["processing_metrics"],
            }

        except Exception:
            # Limpieza en caso de error: eliminar sesión incompleta
            if d.exists() and not (d / "workspace.json").exists():
                shutil.rmtree(d, ignore_errors=True)
            raise
