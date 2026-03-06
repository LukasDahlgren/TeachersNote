import json
import tempfile
from pathlib import Path
from typing import Callable

try:
    from pipeline_steps.progress import ProgressEmitter
except ImportError:  # pragma: no cover - package import fallback
    from backend.pipeline_steps.progress import ProgressEmitter


def run_pipeline_steps(
    pdf_path: str,
    audio_path: str,
    pptx_output_path: str,
    *,
    emit: ProgressEmitter | None,
    on_slides_parsed: Callable[[int], None] | None,
    on_slide_enriched: Callable[[int, dict], None] | None,
    on_pre_enrich: Callable[[list, list, list], None] | None,
    course_context: str | None,
    emit_progress: Callable[[ProgressEmitter | None, str, str, int], None],
    transcribe: Callable[[str, ProgressEmitter | None], list[dict]],
    align: Callable[[list[dict], list[dict], ProgressEmitter | None], list[dict]],
    enrich: Callable[..., list[dict]],
    generate_presentation_from_enhanced: Callable[[str, list[dict], str], None],
    parse_slides: Callable[[str, str], None] | None = None,
) -> dict:
    if parse_slides is None:
        from scripts.parse_slides import parse_slides as default_parse_slides

        parse_slides = default_parse_slides

    print("📄 Parsing slides from PDF...", flush=True)
    emit_progress(emit, "parse_slides", "📄 Parsing slides...", 12)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        slides_tmp = handle.name
    parse_slides(pdf_path, slides_tmp)
    with open(slides_tmp, encoding="utf-8") as handle:
        slides = json.load(handle)
    Path(slides_tmp).unlink(missing_ok=True)
    emit_progress(emit, "parse_slides", f"📄 Extracted {len(slides)} slides.", 22)
    if on_slides_parsed is not None:
        try:
            on_slides_parsed(len(slides))
        except Exception:
            pass

    transcript = transcribe(audio_path, emit)
    alignment = align(slides, transcript, emit)

    if on_pre_enrich is not None:
        try:
            on_pre_enrich(slides, transcript, alignment)
        except Exception:
            pass
    enhanced = enrich(
        slides,
        transcript,
        alignment,
        emit=emit,
        on_slide_enriched=on_slide_enriched,
        course_context=course_context,
    )

    emit_progress(emit, "generate_pptx", "🎉 Generating presentation...", 93)
    generate_presentation_from_enhanced(pdf_path, enhanced, pptx_output_path)
    print("🎉 Pipeline complete!", flush=True)
    emit_progress(emit, "generate_pptx", "🎉 Done!", 98)

    return {
        "slides": slides,
        "transcript": transcript,
        "alignment": alignment,
        "enhanced": enhanced,
        "download_url": f"/download/{Path(pptx_output_path).name}",
    }
