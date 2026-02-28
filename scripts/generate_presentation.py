import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import fitz  # pymupdf
from pptx import Presentation
from pptx.util import Inches, Pt


SLIDE_WIDTH = Inches(13.33)
SLIDE_HEIGHT = Inches(7.5)
BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)")


def pdf_to_images(pdf_path: str, dpi: int = 150) -> list[bytes]:
    """Render each PDF page to PNG bytes in parallel."""
    doc = fitz.open(pdf_path)
    try:
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        page_count = len(doc)

        def render_page(idx: int) -> tuple[int, bytes]:
            pix = doc[idx].get_pixmap(matrix=matrix)
            return idx, pix.tobytes("png")

        with ThreadPoolExecutor() as pool:
            results = list(pool.map(render_page, range(page_count)))
    finally:
        doc.close()
    return [img for _, img in sorted(results)]


def _bulletize_text(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return []

    prefixed_items: list[str] = []
    has_prefixed = False
    for line in lines:
        match = BULLET_PREFIX_RE.match(line)
        if match:
            has_prefixed = True
            item = line[match.end():].strip()
            if item:
                prefixed_items.append(item)
            continue
        if has_prefixed and prefixed_items:
            prefixed_items[-1] = f"{prefixed_items[-1]} {line}".strip()

    if has_prefixed and prefixed_items:
        return prefixed_items

    if len(lines) > 1:
        return lines

    compact = " ".join(normalized.split())
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|;\s+", compact) if p.strip()]
    return parts or ([compact] if compact else [])


def build_speaker_notes(entry: dict) -> str:
    lines = []
    lines.append(f"SAMMANFATTNING: {entry.get('summary', '')}")
    lines.append("")
    la = entry.get("lecturer_additions", "")
    lecturer_bullets = _bulletize_text(la) if la else []
    if lecturer_bullets:
        lines.append("FÖRELÄSARENS TILLÄGG:")
        for item in lecturer_bullets:
            lines.append(f"  • {item}")
        lines.append("")
    takeaways = entry.get("key_takeaways", [])
    if takeaways:
        lines.append("KEY TAKEAWAYS:")
        for t in takeaways:
            lines.append(f"  • {t}")
    return "\n".join(lines)


def generate(pdf_path: str, enhanced_path: str, output_path: str) -> None:
    with open(enhanced_path, encoding="utf-8") as f:
        enhanced = json.load(f)

    enhanced_by_slide = {e["slide"]: e for e in enhanced}

    print("Rendering PDF pages to images...")
    images = pdf_to_images(pdf_path)

    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT

    blank_layout = prs.slide_layouts[6]  # completely blank layout

    for i, img_bytes in enumerate(images, start=1):
        slide = prs.slides.add_slide(blank_layout)

        # Fill the entire slide with the PDF page image (in-memory, no temp file)
        slide.shapes.add_picture(
            BytesIO(img_bytes),
            left=Inches(0),
            top=Inches(0),
            width=SLIDE_WIDTH,
            height=SLIDE_HEIGHT,
        )

        # Add speaker notes
        entry = enhanced_by_slide.get(i)
        if entry:
            notes_text = build_speaker_notes(entry)
            notes_slide = slide.notes_slide
            tf = notes_slide.notes_text_frame
            tf.text = notes_text
            for para in tf.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(11)

        print(f"  Slide {i}/{len(images)} done")

    prs.save(output_path)
    print(f"\nSaved {len(images)}-slide presentation → {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate enriched PPTX from PDF slides + enhanced.json"
    )
    parser.add_argument("--pdf", required=True, help="Original PDF lecture slides")
    parser.add_argument("--enhanced", required=True, help="Path to enhanced.json")
    parser.add_argument("--output", required=True, help="Output .pptx path")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI (default 150)")
    args = parser.parse_args()
    generate(args.pdf, args.enhanced, args.output)
