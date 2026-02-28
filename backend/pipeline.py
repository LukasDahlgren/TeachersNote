import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import anthropic
from groq import Groq

alignment_client = anthropic.Anthropic()

ProgressEmitter = Callable[[str, str, int], None]

# Allow importing from sibling scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.parse_slides import parse_slides
from scripts.align import build_prompt, parse_response
from scripts.enrich import (
    DEFAULT_ENRICH_LOG_USAGE,
    DEFAULT_ENRICH_MAX_ATTEMPTS,
    DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
    DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
    DEFAULT_ENRICH_MAX_WORKERS,
    build_fallback_enrichment,
    create_enrichment_client,
    default_enrichment_model,
    enrich_slide_with_retry,
    is_enriched_payload_invalid,
    normalize_enriched_payload,
    resolve_enrichment_provider,
)
from scripts.generate_presentation import generate as generate_pptx

ENRICH_PROVIDER = resolve_enrichment_provider(os.getenv("ENRICH_PROVIDER"))
ENRICH_MODEL = os.getenv("ENRICH_MODEL", "").strip() or default_enrichment_model(ENRICH_PROVIDER)
ENRICH_MAX_WORKERS = DEFAULT_ENRICH_MAX_WORKERS
ENRICH_MAX_TRANSCRIPT_WORDS = DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS
ENRICH_MAX_OUTPUT_TOKENS = DEFAULT_ENRICH_MAX_OUTPUT_TOKENS
ENRICH_MAX_ATTEMPTS = DEFAULT_ENRICH_MAX_ATTEMPTS
ENRICH_LOG_USAGE = DEFAULT_ENRICH_LOG_USAGE
enrichment_client = create_enrichment_client(ENRICH_PROVIDER)


def enrich_slide_notes(
    slide: dict,
    transcript_text: str,
    max_attempts: int = ENRICH_MAX_ATTEMPTS,
    log_callback=None,
    *,
    return_metrics: bool = False,
) -> dict | tuple[dict, dict]:
    enriched, metrics = enrich_slide_with_retry(
        enrichment_client,
        slide,
        transcript_text,
        provider=ENRICH_PROVIDER,
        model=ENRICH_MODEL,
        max_output_tokens=ENRICH_MAX_OUTPUT_TOKENS,
        max_transcript_words=ENRICH_MAX_TRANSCRIPT_WORDS,
        max_attempts=max_attempts,
        log_usage=ENRICH_LOG_USAGE,
        log_callback=log_callback,
    )
    if return_metrics:
        return enriched, metrics
    return enriched


def generate_presentation_from_enhanced(
    pdf_path: str,
    enhanced: list[dict],
    output_path: str,
) -> None:
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as f:
        json.dump(enhanced, f, ensure_ascii=False)
        enhanced_tmp = f.name
    try:
        generate_pptx(pdf_path, enhanced_tmp, output_path)
    finally:
        Path(enhanced_tmp).unlink(missing_ok=True)


def _emit_progress(
    emit: ProgressEmitter | None,
    stage: str,
    message: str,
    progress_pct: int,
) -> None:
    if emit is None:
        return
    bounded = max(0, min(100, int(progress_pct)))
    emit(stage, message, bounded)


def transcribe(audio_path: str, emit: ProgressEmitter | None = None) -> list[dict]:
    groq_client = Groq()
    print("⏳ Compressing audio...", flush=True)
    _emit_progress(emit, "transcribe", "Compressing audio for transcription...", 28)
    mp3_path = audio_path + ".tmp.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", "-b:a", "32k", mp3_path],
        check=True, capture_output=True,
    )
    print("☁️  Transcribing with Groq Whisper...", flush=True)
    _emit_progress(emit, "transcribe", "Transcribing audio with Whisper...", 35)
    try:
        with open(mp3_path, "rb") as f:
            result = groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
    finally:
        Path(mp3_path).unlink(missing_ok=True)
    segments = [
        {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
        for s in result.segments
    ]
    print(f"✅ Transcription done — {len(segments)} segments", flush=True)
    _emit_progress(emit, "transcribe", f"Transcription complete: {len(segments)} segments.", 48)
    return segments


def align(
    slides: list[dict],
    transcript: list[dict],
    emit: ProgressEmitter | None = None,
) -> list[dict]:
    print("🔗 Aligning transcript to slides via Claude...", flush=True)
    _emit_progress(emit, "align", "Aligning transcript to slides...", 55)
    prompt = build_prompt(slides, transcript)
    message = alignment_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    boundaries = parse_response(message.content[0].text)
    boundaries.sort(key=lambda x: x["slide"])

    result = []
    for i, b in enumerate(boundaries):
        start = b["start_segment"]
        end = (
            boundaries[i + 1]["start_segment"] - 1
            if i + 1 < len(boundaries)
            else len(transcript) - 1
        )
        result.append({"slide": b["slide"], "start_segment": start, "end_segment": end})
    print(f"✅ Alignment done — {len(result)} slides mapped", flush=True)
    _emit_progress(emit, "align", f"Alignment complete: {len(result)} slides mapped.", 65)
    return result


def enrich(
    slides: list[dict],
    transcript: list[dict],
    alignment: list[dict],
    emit: ProgressEmitter | None = None,
) -> list[dict]:
    total = len(alignment)
    done_count = 0
    done_lock = threading.Lock()
    metrics_lock = threading.Lock()
    stage_started = time.perf_counter()
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "retries": 0,
        "fallbacks": 0,
        "duration_ms": 0,
    }
    failure_reason_counts = {
        "truncated_json": 0,
        "empty_payload": 0,
        "connection_error": 0,
        "other_error": 0,
    }

    print(
        f"✨ Enriching {total} slides via {ENRICH_PROVIDER}:{ENRICH_MODEL} "
        f"(workers={ENRICH_MAX_WORKERS}, retries={ENRICH_MAX_ATTEMPTS}, "
        f"max_output_tokens={ENRICH_MAX_OUTPUT_TOKENS}, max_transcript_words={ENRICH_MAX_TRANSCRIPT_WORDS})...",
        flush=True,
    )
    _emit_progress(emit, "enrich", f"Enriching {total} slides...", 70)
    slides_by_num = {s["slide"]: s for s in slides}

    def enrich_one(a: dict) -> dict:
        nonlocal done_count
        slide = slides_by_num[a["slide"]]
        text = " ".join(
            seg["text"].strip()
            for seg in transcript[a["start_segment"]: a["end_segment"] + 1]
        )

        def slide_log(msg: str) -> None:
            with done_lock:
                local_done = done_count
            pct = 70 + int((local_done / total) * 20) if total > 0 else 90
            _emit_progress(emit, "enrich", msg, pct)

        enriched, metrics = enrich_slide_notes(
            slide,
            text,
            max_attempts=ENRICH_MAX_ATTEMPTS,
            log_callback=slide_log,
            return_metrics=True,
        )
        with done_lock:
            done_count += 1
            local_done = done_count
        with metrics_lock:
            usage_totals["input_tokens"] += int(metrics.get("input_tokens", 0))
            usage_totals["output_tokens"] += int(metrics.get("output_tokens", 0))
            usage_totals["total_tokens"] += int(metrics.get("total_tokens", 0))
            usage_totals["retries"] += int(metrics.get("retries", 0))
            usage_totals["duration_ms"] += int(metrics.get("duration_ms", 0))
            if metrics.get("fallback_used"):
                usage_totals["fallbacks"] += 1
                reason = str(metrics.get("failure_reason", "other_error"))
                if reason not in failure_reason_counts:
                    reason = "other_error"
                failure_reason_counts[reason] += 1

        print(f"  ✅ Slide {a['slide']} done ({local_done}/{total})", flush=True)
        if total > 0:
            pct = 70 + int((local_done / total) * 20)
        else:
            pct = 90
        _emit_progress(
            emit,
            "enrich",
            f"Enriched slide {a['slide']} ({local_done}/{total}).",
            pct,
        )
        return {
            "slide": a["slide"],
            "original_text": slide["text"],
            "start_segment": a["start_segment"],
            "end_segment": a["end_segment"],
            **enriched,
        }

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=ENRICH_MAX_WORKERS) as pool:
        futures = [pool.submit(enrich_one, a) for a in alignment]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda x: x["slide"])
    wall_duration_ms = int((time.perf_counter() - stage_started) * 1000)
    summary = (
        f"Slide enrichment complete. total_tokens={usage_totals['total_tokens']} "
        f"(input={usage_totals['input_tokens']}, output={usage_totals['output_tokens']}), "
        f"retries={usage_totals['retries']}, fallbacks={usage_totals['fallbacks']}, "
        f"fallback_reasons=truncated_json:{failure_reason_counts['truncated_json']}"
        f"|empty_payload:{failure_reason_counts['empty_payload']}"
        f"|connection_error:{failure_reason_counts['connection_error']}"
        f"|other_error:{failure_reason_counts['other_error']}, "
        f"api_duration_ms={usage_totals['duration_ms']}, wall_duration_ms={wall_duration_ms}"
    )
    print(f"✅ {summary}", flush=True)
    _emit_progress(emit, "enrich", summary, 90)
    return results


def run_pipeline(
    pdf_path: str,
    audio_path: str,
    pptx_output_path: str,
    emit: ProgressEmitter | None = None,
) -> dict:
    # Step 1: Extract slides
    print("📄 Parsing slides from PDF...", flush=True)
    _emit_progress(emit, "parse_slides", "Parsing slides from PDF...", 12)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        slides_tmp = f.name
    parse_slides(pdf_path, slides_tmp)
    with open(slides_tmp, encoding="utf-8") as f:
        slides = json.load(f)
    Path(slides_tmp).unlink(missing_ok=True)
    _emit_progress(emit, "parse_slides", f"Parsed {len(slides)} slides from PDF.", 22)

    # Step 2: Transcribe audio
    transcript = transcribe(audio_path, emit=emit)

    # Step 3: Align
    alignment = align(slides, transcript, emit=emit)

    # Step 4: Enrich
    enhanced = enrich(slides, transcript, alignment, emit=emit)

    # Step 5: Generate PPTX
    _emit_progress(emit, "generate_pptx", "Generating PPTX output...", 93)
    generate_presentation_from_enhanced(pdf_path, enhanced, pptx_output_path)
    print("🎉 Pipeline complete!", flush=True)
    _emit_progress(emit, "generate_pptx", "PPTX generation complete.", 98)

    return {
        "slides": slides,
        "transcript": transcript,
        "alignment": alignment,
        "enhanced": enhanced,
        "download_url": f"/download/{Path(pptx_output_path).name}",
    }
