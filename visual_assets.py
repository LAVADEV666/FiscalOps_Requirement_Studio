from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pdfplumber
import pymupdf

from audit_engine import POINT_LINE, _group_lines


LINE_SETTINGS = {
    "snap_tolerance": 4, "join_tolerance": 4, "intersection_tolerance": 5,
}
FIGURE_TYPES = {"figure", "image", "chart"}


def _area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _intersection(a, b):
    return max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])


def _overlap(box, other):
    return _area(_intersection(box, other)) / max(1, _area(box))


def _visible_box(box, page):
    box = _intersection(box, page.cropbox)
    if box[2] - box[0] >= 15 and box[3] - box[1] >= 15 and _area(box) >= 450:
        return box
    return None


def _positioned_lines(words):
    """Separate cells only at gaps wider than normal spaces in a paragraph."""
    grouped = defaultdict(list)
    for word in sorted(words, key=lambda item: item["top"]):
        top = next(reversed(grouped), None)
        grouped[top if top is not None and word["top"] - top <= 3 else word["top"]].append(word)
    for top, line in grouped.items():
        cells = []
        for word in sorted(line, key=lambda item: item["x0"]):
            if cells and word["x0"] - cells[-1][1] < 16:
                cells[-1][1] = max(cells[-1][1], word["x1"])
                cells[-1][2] += " " + word["text"]
            else:
                cells.append([word["x0"], word["x1"], word["text"]])
        yield top, max(word["bottom"] for word in line), cells


def _borderless_tables(words):
    """Recognize runs of three or more consistently aligned rows."""
    run = []
    for top, bottom, cells in [*_positioned_lines(words), (0, 0, [])]:
        aligned = False
        if run and 2 <= len(cells) == len(run[0][2]):
            step = top - run[-1][0]
            aligned = 7 <= step <= 36 and all(
                min(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 3
                for a, b in zip(run[0][2], cells)
            )
        if run and not aligned:
            if len(run) >= 3:
                box = (min(r[2][0][0] for r in run), run[0][0],
                       max(r[2][-1][1] for r in run), run[-1][1])
                yield box, [[cell[2] for cell in row[2]] for row in run]
            run = []
        if len(cells) >= 2:
            run.append((top, bottom, cells))


def detect_native_tables(page, words):
    ruled = []
    for table in page.find_tables(LINE_SETTINGS):
        box = _visible_box(table.bbox, page)
        if not box or len(table.rows) < 2 or len(table.columns) < 2:
            continue
        ruled.append(box)
        rows = [[cell or "" for cell in row] for row in table.extract()]
        # A missing grid cell indicates a merge or an irregular table.
        editable = box == table.bbox and all(cell is not None for row in table.rows for cell in row.cells)
        yield box, rows if editable else [], 0.96
    outside = [
        word for word in words
        if not any(_overlap((word["x0"], word["top"], word["x1"], word["bottom"]), box) > 0.5
                   for box in ruled)
    ]
    for box, rows in _borderless_tables(outside):
        visible = _visible_box(box, page)
        if visible:
            yield visible, rows if visible == box else [], 0.80


def _scan_candidates(page, result):
    width, height = result.get("layout_size") or (0, 0)
    if not (width and height):
        return
    x0, y0, x1, y1 = page.cropbox
    sx, sy = (x1 - x0) / width, (y1 - y0) / height
    for kind, items in (("table", result.get("tables", [])), ("image", result.get("regions", []))):
        for item in items:
            if kind == "image" and item.get("type") not in FIGURE_TYPES:
                continue
            left, top, right, bottom = item["bbox"]
            yield kind, (x0 + left * sx, y0 + top * sy, x0 + right * sx, y0 + bottom * sy), item.get("confidence", 0)


def _vector_candidates(page, origin):
    cluster_drawings = getattr(page, "cluster_drawings", None)
    if cluster_drawings is None:
        return
    x0, y0 = origin
    for drawing in cluster_drawings():
        if drawing.width < 35 or drawing.height < 25 or drawing.get_area() < 1200:
            continue
        if drawing.get_area() >= 0.75 * page.rect.get_area():
            continue
        box = drawing * page.rotation_matrix
        yield box.x0 + x0, box.y0 + y0, box.x1 + x0, box.y1 + y0


def _point_starts(points, pages):
    """Find the start of each numeral on its first page."""
    starts = []
    for point in points:
        page = point["page_start"]
        top = next((line["top"] for line in pages[page]
                    if (match := POINT_LINE.match(line["text"]))
                    and int(match[1]) == int(point["number"])), 0)
        starts.append(((page, top), point))
    return sorted(starts, key=lambda entry: entry[0])


def _write_asset(page, target, assets, page_no, kind, box, rows, confidence):
    prefix = "T" if kind == "table" else "I"
    index = len(assets) + 1
    file = f"p{page_no:03d}_{kind}_{index:03d}.png"
    image = page.crop(box, strict=False).to_image(resolution=220, antialias=True).original.convert("RGB")
    image.save(target / file)
    title = "Tabla" if kind == "table" else "Imagen"
    assets.append({
        "asset_id": f"AST-{prefix}-{page_no:03d}-{index:03d}", "type": kind,
        "page": page_no, "bbox": list(box), "file": file,
        "mode": "editable" if rows else "image", "rows": rows, "include": True,
        "caption": f"{title} · página {page_no}", "confidence": confidence,
        "width": image.width, "height": image.height,
    })


def extract_visual_assets(
    pdf_path: Path, target: Path, points: list[dict[str, Any]],
    ocr_pages: list[dict[str, Any]] | None = None,
    native_tables: dict[int, list] | None = None,
) -> list[dict[str, Any]]:
    target.mkdir(parents=True, exist_ok=True)
    ocr_by_page = {item["page"]: item for item in ocr_pages or []}
    assets, lines = [], {}
    with pdfplumber.open(pdf_path) as pdf, pymupdf.open(pdf_path) as vector_pdf:
        # Reused images at the margins are usually letterhead or page footers.
        margin_pages = defaultdict(set)
        for page in pdf.pages:
            for image in page.images:
                if image["stream"].objid is not None and (
                    image["top"] < page.bbox[1] + 110 or image["bottom"] > page.bbox[3] - 100
                ):
                    margin_pages[image["stream"].objid].add(page.page_number)
        for page in pdf.pages:
            page_no = page.page_number
            scan = ocr_by_page.get(page_no)
            words = page.extract_words()
            lines[page_no] = _group_lines(words)
            if scan and scan.get("height"):
                top, bottom = page.cropbox[1], page.cropbox[3]
                lines[page_no] = [
                    {"text": block["text"], "top": top + block["bbox"][1] * (bottom - top) / scan["height"]}
                    for block in scan.get("text_blocks", [])
                ]
            boxes = []
            tables = native_tables.get(page_no) if native_tables is not None else None
            if tables is None:
                tables = list(detect_native_tables(page, words))
            if tables and not scan:
                lines[page_no] = _group_lines([
                    word for word in words if not any(
                        _overlap((word["x0"], word["top"], word["x1"], word["bottom"]), box) > 0.5
                        for box, _, _ in tables
                    )
                ])
            candidates = [("table", box, rows, score) for box, rows, score in tables]
            if scan:
                candidates.extend((kind, box, [], score) for kind, box, score in _scan_candidates(page, scan))
            for image in page.images:
                box = (image["x0"], image["top"], image["x1"], image["bottom"])
                if page_no in margin_pages[image["stream"].objid] and len(margin_pages[image["stream"].objid]) > 1:
                    continue
                if _area(box) < 0.75 * _area(page.bbox):
                    candidates.append(("image", box, [], 0.84))
            if not scan:
                candidates.extend(
                    ("image", box, [], 0.76)
                    for box in _vector_candidates(vector_pdf[page_no - 1], page.cropbox[:2])
                )
            for kind, box, rows, confidence in candidates:
                box = _visible_box(box, page)
                if not box:
                    continue
                if any(_overlap(box, seen) > 0.75 or _overlap(seen, box) > 0.75 for seen in boxes):
                    continue
                _write_asset(page, target, assets, page_no, kind, box, rows, confidence)
                boxes.append(box)

    assets.sort(key=lambda asset: (asset["page"], asset["bbox"][1], asset["bbox"][0]))
    for point in points:
        point["asset_ids"] = []
    starts = _point_starts(points, lines)
    if starts:
        for asset in assets:
            position = (asset["page"], (asset["bbox"][1] + asset["bbox"][3]) / 2)
            owner = next((point for start, point in reversed(starts) if start <= position), starts[0][1])
            owner["asset_ids"].append(asset["asset_id"])
    return assets
