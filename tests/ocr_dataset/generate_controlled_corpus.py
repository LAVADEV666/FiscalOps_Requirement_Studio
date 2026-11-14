"""Generate a deterministic, non-sensitive corpus for hybrid OCR QA.

The generated PDFs contain synthetic identifiers and are written to the output
directory supplied by the caller.  They are useful for routing, coverage and
regression checks, but they are not a substitute for a human-validated fiscal
reference corpus.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


CATEGORIES = ("digital", "scanned_good", "scanned_regular", "scanned_bad")
PAGE_SIZE = (612, 792)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        import PIL

        bundled = Path(PIL.__file__).parent / "fonts" / "DejaVuSans.ttf"
        return ImageFont.truetype(str(bundled), size)
    except Exception:
        return ImageFont.load_default()


def reference_text(category: str, index: int) -> str:
    return "\n".join((
        f"REQUERIMIENTO SINTETICO {category.upper()} {index:02d}",
        "SERVICIO DE ADMINISTRACION TRIBUTARIA",
        "RFC ABC010101XX0",
        f"NUMERO DE OFICIO 500-01-2026-{index:03d}",
        "PERIODO 2025",
        "IMPORTE $10,000.00",
        "1. Proporcione la documentacion del periodo 2025.",
        "2. Aclare el importe de $10,000.00.",
    ))


def mixed_reference_text(index: int = 1) -> str:
    base = reference_text("mixed", index).splitlines()
    return "\n".join([*base[:4], "ANEXO VISUAL 2025", "IMPORTE $10,000.00"])


def _image_for(text: str, category: str, seed: int) -> Image.Image:
    sizes = {
        "scanned_good": (1800, 2400),
        "scanned_regular": (1200, 1600),
        "scanned_bad": (760, 1020),
    }
    width, height = sizes[category]
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font(max(22, width // 42))
    y = max(36, height // 14)
    for line in text.splitlines():
        draw.text((width // 12, y), line, fill="black", font=font)
        y += int(font.size * 1.8) if hasattr(font, "size") else 48
    if category == "scanned_regular":
        image = image.resize((width - 100, height - 120), Image.Resampling.BILINEAR)
        image = image.filter(ImageFilter.GaussianBlur(0.45))
    elif category == "scanned_bad":
        image = image.rotate(-1.2, expand=True, fillcolor="#ededed")
        image = image.resize((int(image.width * 0.82), int(image.height * 0.82)), Image.Resampling.BILINEAR)
        image = image.filter(ImageFilter.GaussianBlur(0.9))
        rng = random.Random(seed)
        pixels = image.load()
        for _ in range(max(1, image.width * image.height // 1800)):
            x = rng.randrange(image.width)
            y = rng.randrange(image.height)
            shade = rng.randrange(150, 235)
            pixels[x, y] = (shade, shade, shade)
    return image


def _draw_scanned_page(pdf: canvas.Canvas, image: Image.Image) -> None:
    image_path = Path(pdf._filename).with_suffix(".page.png")
    image.save(image_path, format="PNG")
    try:
        pdf.drawImage(ImageReader(str(image_path)), 0, 0, width=PAGE_SIZE[0], height=PAGE_SIZE[1], preserveAspectRatio=True, anchor="c", mask="auto")
    finally:
        image_path.unlink(missing_ok=True)


def _digital_pdf(path: Path, text: str, *, pages: int = 1) -> None:
    pdf = canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    for page_number in range(1, pages + 1):
        pdf.setFont("Helvetica", 11)
        y = 750
        for line in text.splitlines():
            pdf.drawString(48, y, line)
            y -= 25
        if pages > 1:
            pdf.drawString(48, 100, f"PAGINA {page_number} DE {pages}")
        pdf.showPage()
    pdf.save()


def _scanned_pdf(path: Path, text: str, category: str, seed: int) -> None:
    pdf = canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    image = _image_for(text, category, seed)
    _draw_scanned_page(pdf, image)
    pdf.showPage()
    pdf.save()


def _mixed_pdf(path: Path, text: str, seed: int) -> None:
    pdf = canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    pdf.setFont("Helvetica", 11)
    for line_number, line in enumerate(text.splitlines()[:4]):
        pdf.drawString(48, 750 - line_number * 24, line)
    image = _image_for("ANEXO VISUAL 2025\nIMPORTE $10,000.00", "scanned_good", seed)
    image_path = path.with_suffix(".mixed.png")
    image.save(image_path, format="PNG")
    try:
        pdf.drawImage(ImageReader(str(image_path)), 48, 120, width=516, height=330, preserveAspectRatio=True, anchor="c", mask="auto")
    finally:
        image_path.unlink(missing_ok=True)
    pdf.showPage()
    pdf.save()


def generate_corpus(output: str | Path, *, per_category: int = 10, include_special: bool = True) -> dict:
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for category in CATEGORIES:
        for index in range(1, per_category + 1):
            text = reference_text(category, index)
            name = f"{category}-{index:02d}.pdf"
            path = root / name
            if category == "digital":
                _digital_pdf(path, text)
            else:
                _scanned_pdf(path, text, category, index)
            rows.append({
                "pdf": name,
                "page": 1,
                "category": category,
                "text": text,
                "ground_truth_status": "verified",
                "ground_truth_origin": "synthetic_generator",
                "anonymization_certified": True,
            })
    if include_special:
        mixed_text = mixed_reference_text(1)
        mixed_name = "special-mixed.pdf"
        _mixed_pdf(root / mixed_name, mixed_text, 9001)
        rows.append({"pdf": mixed_name, "page": 1, "category": "mixed", "text": mixed_text, "ground_truth_status": "verified", "ground_truth_origin": "synthetic_generator", "anonymization_certified": True})
        multipage_name = "special-multipage.pdf"
        _digital_pdf(root / multipage_name, reference_text("multipage", 1), pages=2)
        for page in (1, 2):
            rows.append({"pdf": multipage_name, "page": page, "category": "multipage", "text": reference_text("multipage", 1), "ground_truth_status": "verified", "ground_truth_origin": "synthetic_generator", "anonymization_certified": True})
    manifest = root / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    metadata = {"generator": "fiscalops.controlled-corpus.v1", "cases": len(rows), "per_category": per_category, "categories": sorted({row["category"] for row in rows}), "synthetic_only": True}
    (root / "corpus_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**metadata, "manifest": str(manifest), "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generar corpus sintético reproducible de QA híbrido")
    parser.add_argument("output", type=Path)
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--no-special", action="store_true")
    args = parser.parse_args()
    result = generate_corpus(args.output, per_category=max(1, args.per_category), include_special=not args.no_special)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
