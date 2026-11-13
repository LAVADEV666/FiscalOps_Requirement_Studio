"""
document_model.py — Modelos de datos espaciales y lógica de árbol jerárquico.

Contiene dos capas:
  1. Capa espacial (dataclasses / pydantic) para texto con coordenadas,
     tablas estructuradas y reconstrucción de jerarquía (numerales → incisos).
  2. Capa documental (dict-based, heredada) para compatibilidad con
     word_builder, tests y el resto del pipeline.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Versión del esquema documental
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "fiscalops.document.v2-spatial"
BLOCK_TYPES = {"requirement_text", "response_text", "support_list", "asset", "page_break", "table_block"}

# ---------------------------------------------------------------------------
# Modelo espacial: TextBlock
# ---------------------------------------------------------------------------

@dataclass
class TextBlock:
    """
    Bloque de texto con su posición espacial en la página.

    Atributos:
        text:           Contenido textual del bloque.
        x0, y0, x1, y1: Coordenadas del bounding box (píxeles, origen arriba-izq).
        block_id:       Identificador único (opcional).
        confidence:     Confianza del OCR (0.0 – 1.0).
        source:         Origen del bloque: 'native' (fitz) o 'ocr'.
    """
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    block_id: str = ""
    confidence: float = 1.0
    source: str = "native"

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def indent_level(self) -> float:
        """Sangría relativa medida desde el borde izquierdo (x0)."""
        return self.x0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "x0": round(self.x0, 2),
            "y0": round(self.y0, 2),
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
            "block_id": self.block_id,
            "confidence": self.confidence,
            "source": self.source,
            "center_x": round(self.center_x, 2),
            "indent_level": round(self.indent_level, 2),
        }


# ---------------------------------------------------------------------------
# Modelo espacial: TableBlock
# ---------------------------------------------------------------------------

@dataclass
class TableBlock:
    """
    Representa una tabla detectada por PP-Structure.

    Atributos:
        rows:      Lista de listas; cada sublista es una fila de celdas.
        header:    Lista de encabezados (opcional).
        bbox:      [x0, y0, x1, y1] en píxeles.
        confidence: Confianza de detección.
    """
    rows: list[list[str]]
    bbox: list[float] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    confidence: float = 1.0
    table_id: str = ""

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "rows": self.rows,
            "header": self.header,
            "bbox": self.bbox,
            "n_rows": self.n_rows,
            "n_cols": self.n_cols,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Nodo del árbol jerárquico
# ---------------------------------------------------------------------------

@dataclass
class HierarchicalNode:
    """
    Nodo del árbol que representa un numeral o inciso.

    Atributos:
        text:       Contenido del bloque.
        indent:     Sangría absoluta (x0).
        level:      Profundidad en el árbol (0 = numeral principal).
        block:      Referencia al TextBlock original.
        children:   Sub-nodos (incisos).
    """
    text: str
    indent: float
    level: int
    block: TextBlock
    children: list["HierarchicalNode"] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def walk(self) -> Iterator["HierarchicalNode"]:
        """Recorrido pre-orden sobre el árbol."""
        yield self
        for child in self.children:
            yield from child.walk()


# ---------------------------------------------------------------------------
# Lógica computacional de jerarquía basada en coordenadas X
# ---------------------------------------------------------------------------

def _classify_line_type(text: str) -> str | None:
    """
    Clasifica una línea según su prefijo numérico/alfabético.

    Retorna:
        'numeral'    → patrones como '1.', '1)', '1 -'
        'inciso_a'   → 'a)', 'a.', '(a)', 'a)'
        'inciso_b'   → 'b)', 'b.', etc.
        'subinciso'  → 'i.', 'i)', '1.1', etc.
        None         → texto normal sin marcador
    """
    import re
    # Numeral principal: dígito(s) seguido de punto, guión o paréntesis
    if re.match(r"^\s*(\d{1,3})\s*[.)\-–—]\s+", text):
        return "numeral"
    # Romanos PRIMERO que letras genéricas: i), ii), iii, iv, v, x
    # Debe ir antes del patrón [a-z] porque "i)" coincidiría como "inciso".
    if re.match(r"^\s*(i{1,4}|v|x)\s*[.)]\s+", text, re.I):
        return "subinciso"
    # Letra minúscula con paréntesis o punto: a), b), c), etc.
    if re.match(r"^\s*([a-záéíóúñ])\s*[.)]\s+", text, re.I):
        return "inciso"
    # Sub-inciso con dígitos encadenados: 1.1, 1.1.1
    if re.match(r"^\s*(\d+\.\d+(?:\.\d+)?)\s*[.)\-–—]?\s+", text):
        return "subinciso"
    return None


def _parse_numeral(text: str) -> str | None:
    """Extrae el identificador numérico de una línea (ej: '1', 'a', 'i')."""
    import re
    m = re.match(r"^\s*(\d{1,3}|[a-záéíóúñ]|i{1,4}|v|x)\s*[.)\-–—]", text, re.I)
    return m.group(1) if m else None


def build_hierarchy(text_blocks: list[TextBlock]) -> HierarchicalNode:
    """
    Reconstruye la estructura jerárquica de un documento fiscal a partir
    de bloques de texto con coordenadas X.

    Algoritmo (computacional, NO expresiones regulares simples):
      1. Ordenar bloques por coordenada Y (top → bottom).
      2. Para cada bloque, clasificar su tipo (numeral, inciso, subinciso).
      3. Comparar la sangría X con la del bloque anterior:
         - Si X actual > X anterior + umbral → es hijo (inciso/subinciso).
         - Si X actual <= X anterior           → es hermano o ancestro.
      4. Construir árbol manteniendo un stack de niveles activos.

    Parámetros:
        text_blocks: Lista de TextBlock con coordenadas válidas.

    Retorna:
        Raíz del árbol HierarchicalNode.
    """
    if not text_blocks:
        root = HierarchicalNode(text="", indent=-1.0, level=-1,
                                block=TextBlock(text="", x0=0, y0=0, x1=0, y1=0),
                                children=[])
        return root

    # 1. Ordenar por posición vertical (centro-y)
    sorted_blocks = sorted(text_blocks, key=lambda b: b.center_y)

    # 2. Calcular umbral de sangría dinámico
    #    Usamos el 80% del ancho de página estimado como referencia.
    max_x = max(b.x1 for b in sorted_blocks) if sorted_blocks else 1000
    indent_threshold = max_x * 0.08  # 8% del ancho = mínima sangría significativa

    # 3. Stack de nodos activos por nivel
    #    Cada entrada: (level, node, base_indent)
    stack: list[tuple[int, HierarchicalNode, float]] = []
    root = HierarchicalNode(text="[ROOT]", indent=-1.0, level=-1,
                            block=TextBlock(text="", x0=0, y0=0, x1=0, y1=0),
                            children=[])
    stack.append((0, root, -1.0))

    for block in sorted_blocks:
        raw = block.text.strip()
        if not raw:
            continue

        line_type = _classify_line_type(raw)
        if line_type is None:
            # Texto sin marcador: lo adyuntamos al último nodo visible
            if stack:
                parent = stack[-1][1]
                parent.children.append(HierarchicalNode(
                    text=raw,
                    indent=block.indent_level,
                    level=parent.level + 1,
                    block=block,
                    children=[],
                ))
            continue

        current_indent = block.indent_level
        current_level = 0

        if line_type == "numeral":
            current_level = 0
        elif line_type == "inciso":
            current_level = 1
        elif line_type == "subinciso":
            current_level = 2
        else:
            current_level = 1

        # Determinar padre según sangría y nivel.
        # Buscamos el nodo más profundo en el stack cuyo indent es
        # ESCRICTAMENTE menor que el actual; así items con igual indent
        # (hermanos) no se convierten en padre/hijo entre sí.
        parent_node = root
        parent_level = -1
        parent_indent = -1.0

        for lvl, node, ind in reversed(stack):
            if ind < current_indent and lvl < current_level:
                parent_node = node
                parent_level = lvl
                parent_indent = ind
                break

        # Crear nuevo nodo
        new_node = HierarchicalNode(
            text=raw,
            indent=current_indent,
            level=current_level,
            block=block,
            children=[],
        )

        # Agregar al padre encontrado
        parent_node.children.append(new_node)

        # Actualizar stack: pop nodos cuyo nivel es >= al actual
        # O cuyo indent es >= al actual (hermanos con misma sangría).
        # Usamos > en lugar de >= para que items con igual indent
        # se mantengan como hermanos y no se eliminen prematuramente.
        while stack and (stack[-1][0] >= current_level or stack[-1][2] > current_indent):
            stack.pop()
        stack.append((current_level, new_node, current_indent))

    return root


def hierarchy_to_dict(node: HierarchicalNode, depth: int = 0) -> dict[str, Any]:
    """Convierte un árbol jerárquico a diccionario serializable."""
    result: dict[str, Any] = {
        "text": node.text,
        "indent": node.indent,
        "level": node.level,
        "children": [hierarchy_to_dict(c, depth + 1) for c in node.children],
    }
    if node.block:
        result["block"] = node.block.to_dict()
    return result


def flatten_hierarchy(node: HierarchicalNode) -> list[tuple[int, str, float]]:
    """
    Aplanado pre-orden del árbol.

    Retorna lista de (nivel, texto, sangría_x).
    """
    result: list[tuple[int, str, float]] = []
    for n in node.walk():
        if n.text and n.text != "[ROOT]":
            result.append((n.level, n.text, n.indent))
    return result


# ==============================================================================
# Capa documental heredada (dict-based) — COMPATIBILIDAD CON TESTS
# ==============================================================================

def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def block(block_id: str, kind: str, **values: Any) -> dict[str, Any]:
    """Crea un bloque documental con ID y tipo validados."""
    if kind not in BLOCK_TYPES:
        raise ValueError(f"Tipo de bloque no permitido: {kind}")
    return {"block_id": block_id, "type": kind, "version": 1, **values}


def build_document(data: dict[str, Any]) -> dict[str, Any]:
    """
    Construye el modelo documental canónico a partir de los puntos extraídos.

    Mantiene la estructura de dict original para compatibilidad con
    word_builder, tests y el resto del pipeline.
    """
    sections: list[dict[str, Any]] = []
    assets = {a.get("asset_id"): a for a in data.get("assets", [])}

    for point in data.get("points", []):
        rid = point.get("requirement_id") or f"REQ-{int(point['number']):03d}"
        blocks = [
            block(f"{rid}-REQ", "requirement_text",
                  text=point.get("text", ""),
                  source_fragment_ids=point.get("fragment_ids", [])),
        ]
        for aid in point.get("asset_ids", []):
            if aid in assets:
                blocks.append(block(f"{rid}-{aid}", "asset", asset_id=aid))
        blocks.extend([
            block(f"{rid}-RESP", "response_text",
                  text=point.get("response_text", "[DESARROLLAR RESPUESTA]")),
            block(f"{rid}-SUP", "support_list",
                  items=point.get("support_items", [])),
        ])
        sections.append({
            "section_id": rid,
            "requirement_id": rid,
            "number": point.get("number"),
            "blocks": blocks,
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 1,
        "updated_at": now(),
        "sections": sections,
    }


def ensure_document(data: dict[str, Any]) -> dict[str, Any]:
    """
    Asegura que data contiene un documento válido; lo construye si falta.
    """
    document = data.get("document")
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        data["document"] = build_document(data)
    sync_points_from_document(data)
    return data["document"]


def valid_editor_paragraphs(paragraphs: Any, text: str) -> bool:
    if not isinstance(paragraphs, list):
        return False
    lines = []
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict) or paragraph.get("kind") not in (
            "paragraph", "heading", "subheading", "quote", "bullet", "number", "break",
        ):
            return False
        if paragraph.get("align") not in (None, "left", "center", "right", "justify"):
            return False
        if paragraph["kind"] == "break":
            continue
        runs = paragraph.get("runs")
        if not isinstance(runs, list):
            return False
        for run in runs:
            if not isinstance(run, dict) or not isinstance(run.get("text"), str):
                return False
            if any(not isinstance(run[key], str) for key in ("font", "color") if key in run):
                return False
        lines.append("".join(run["text"] for run in runs))
    return " ".join(" ".join(lines).split()) == " ".join(text.split())


def validate_document(document: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Valida la integridad del modelo documental.
    """
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    assets = {a.get("asset_id") for a in (data or {}).get("assets", [])}

    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append("Versión de esquema documental inválida.")

    for section in document.get("sections", []):
        rid = section.get("requirement_id", "")
        if not rid:
            errors.append("Sección sin requirement_id.")
        types: list[str] = []
        for item in section.get("blocks", []):
            bid = item.get("block_id")
            kind = item.get("type")
            types.append(kind)
            if not bid or bid in seen:
                errors.append(f"Bloque duplicado o vacío: {bid}")
            seen.add(bid)
            if kind not in BLOCK_TYPES:
                errors.append(f"Tipo de bloque inválido: {kind}")
            if kind == "asset" and item.get("asset_id") not in assets:
                errors.append(f'Activo inexistente: {item.get("asset_id")}')
            if kind in {"requirement_text", "response_text"} and "paragraphs" in item:
                if not isinstance(item.get("text"), str) or not valid_editor_paragraphs(item["paragraphs"], item["text"]):
                    errors.append(f"Formato de texto inválido en {bid}.")
        if "requirement_text" not in types:
            errors.append(f"{rid} sin texto de requerimiento.")
        if "response_text" not in types:
            warnings.append(f"{rid} sin bloque de respuesta.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "block_count": len(seen),
    }


def sync_points_from_document(data: dict[str, Any]) -> None:
    """Sincroniza los puntos con los bloques del documento canónico."""
    by_id = {p.get("requirement_id"): p for p in data.get("points", [])}
    for section in data.get("document", {}).get("sections", []):
        point = by_id.get(section.get("requirement_id"))
        if not point:
            continue
        point["asset_ids"] = []
        for item in section.get("blocks", []):
            if item.get("type") == "requirement_text":
                point["text"] = item.get("text", "")
            elif item.get("type") == "response_text":
                point["response_text"] = item.get("text", "")
            elif item.get("type") == "support_list":
                point["support_items"] = item.get("items", [])
            elif item.get("type") == "asset":
                point["asset_ids"].append(item.get("asset_id"))


def update_document(data: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """
    Actualiza el documento con validación e incremento de revisión.
    """
    candidate = deepcopy(document)
    result = validate_document(candidate, data)
    if not result["valid"]:
        raise ValueError("; ".join(result["errors"]))
    old = int(data.get("document", {}).get("revision", 0))
    candidate["revision"] = old + 1
    candidate["updated_at"] = now()
    data["document"] = candidate
    sync_points_from_document(data)
    return result


# ==============================================================================
# Integración: conversión de resultados OCR/fitz → TextBlock / TableBlock
# ==============================================================================

def ocr_result_to_textblocks(
    ocr_result: dict[str, Any],
    page_number: int = 1,
    source: str = "ocr",
) -> list[TextBlock]:
    """
    Convierte el resultado de OCREngine.run() en una lista de TextBlock.

    Cada bloque de texto con coordenadas bbox se mapea a un TextBlock.
    """
    blocks: list[TextBlock] = []
    for tb in ocr_result.get("text_blocks", []):
        bbox = tb.get("bbox", [0, 0, 0, 0])
        if len(bbox) >= 4:
            blocks.append(TextBlock(
                text=tb.get("text", ""),
                x0=bbox[0], y0=bbox[1],
                x1=bbox[2], y1=bbox[3],
                block_id=f"tb-{page_number}-{len(blocks)}",
                confidence=tb.get("confidence", 0.0),
                source=source,
            ))
    return blocks


def ocr_result_to_tables(
    ocr_result: dict[str, Any],
    page_number: int = 1,
) -> list[TableBlock]:
    """
    Convierte tablas detectadas por PP-Structure en TableBlock.
    """
    tables: list[TableBlock] = []
    for t in ocr_result.get("tables", []):
        tables.append(TableBlock(
            rows=t.get("rows", []),
            bbox=t.get("bbox", []),
            header=t.get("header", []),
            confidence=t.get("confidence", 0.0),
            table_id=f"tbl-{page_number}-{len(tables)}",
        ))
    return tables
