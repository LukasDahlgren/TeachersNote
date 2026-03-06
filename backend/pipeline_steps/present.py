import json
import tempfile
from pathlib import Path

from scripts.generate_presentation import generate as generate_pptx


def generate_presentation_from_enhanced(
    pdf_path: str,
    enhanced: list[dict],
    output_path: str,
) -> None:
    with tempfile.NamedTemporaryFile(
        suffix=".json",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as handle:
        json.dump(enhanced, handle, ensure_ascii=False)
        enhanced_tmp = handle.name
    try:
        generate_pptx(pdf_path, enhanced_tmp, output_path)
    finally:
        Path(enhanced_tmp).unlink(missing_ok=True)
