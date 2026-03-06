import json
import os
import random
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

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"), override=False)

from scripts.parse_slides import parse_slides
from scripts.align import build_prompt, parse_response
from scripts.enrich import (
    DEFAULT_ENRICH_BATCH_SIZE,
    DEFAULT_ENRICH_LOG_USAGE,
    DEFAULT_ENRICH_MAX_ATTEMPTS,
    DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
    DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
    DEFAULT_ENRICH_MAX_WORKERS,
    build_fallback_enrichment,
    create_enrichment_client,
    default_enrichment_model,
    enrich_slides_batch_with_retry,
    enrich_slide_with_retry,
    is_enriched_payload_invalid,
    normalize_enriched_payload,
    resolve_enrichment_provider,
)
from scripts.generate_presentation import generate as generate_pptx
from scripts.model_config import resolve_alignment_model, resolve_alignment_model_alias


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(minimum, value)


ENRICH_PROVIDER = resolve_enrichment_provider(os.getenv("ENRICH_PROVIDER"))
ENRICH_MODEL = os.getenv("ENRICH_MODEL", "").strip() or default_enrichment_model(ENRICH_PROVIDER)
ENRICH_BATCH_SIZE = DEFAULT_ENRICH_BATCH_SIZE
ENRICH_MAX_WORKERS = DEFAULT_ENRICH_MAX_WORKERS
ENRICH_MAX_TRANSCRIPT_WORDS = DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS
ENRICH_MAX_OUTPUT_TOKENS = DEFAULT_ENRICH_MAX_OUTPUT_TOKENS
ENRICH_MAX_ATTEMPTS = DEFAULT_ENRICH_MAX_ATTEMPTS
ENRICH_LOG_USAGE = DEFAULT_ENRICH_LOG_USAGE
enrichment_client = create_enrichment_client(ENRICH_PROVIDER)
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "whisper-large-v3-turbo").strip() or "whisper-large-v3-turbo"
TRANSCRIBE_TARGET_BITRATE = os.getenv("TRANSCRIBE_TARGET_BITRATE", "32k").strip() or "32k"
TRANSCRIBE_MAX_UPLOAD_BYTES = _env_int("TRANSCRIBE_MAX_UPLOAD_BYTES", 24_000_000, minimum=1_000_000)
TRANSCRIBE_CHUNK_HEADROOM_PCT = _env_int("TRANSCRIBE_CHUNK_HEADROOM_PCT", 90, minimum=50)
TRANSCRIBE_MIN_CHUNK_SECONDS = _env_int("TRANSCRIBE_MIN_CHUNK_SECONDS", 300, minimum=60)
TRANSCRIBE_RETRY_ATTEMPTS = _env_int("TRANSCRIBE_RETRY_ATTEMPTS", 3, minimum=1)
TRANSCRIBE_RETRY_BASE_DELAY_SECONDS = float(os.getenv("TRANSCRIBE_RETRY_BASE_DELAY_SECONDS", "3").strip() or "3")
TRANSCRIBE_PARALLEL_WORKERS = _env_int("TRANSCRIBE_PARALLEL_WORKERS", 2, minimum=1)
TRANSCRIBE_GLOBAL_MAX_CONCURRENT = _env_int("TRANSCRIBE_GLOBAL_MAX_CONCURRENT", 4, minimum=1)
TRANSCRIBE_PARALLEL_MIN_CHUNKS = _env_int("TRANSCRIBE_PARALLEL_MIN_CHUNKS", 2, minimum=1)
TRANSCRIBE_SAFE_BYTES = max(
    1_000_000,
    int(TRANSCRIBE_MAX_UPLOAD_BYTES * (TRANSCRIBE_CHUNK_HEADROOM_PCT / 100)),
)
ALIGN_MAX_TRANSCRIPT_SEGMENTS = _env_int("ALIGN_MAX_TRANSCRIPT_SEGMENTS", 450, minimum=100)
ALIGN_MAX_SEGMENT_CHARS = _env_int("ALIGN_MAX_SEGMENT_CHARS", 180, minimum=40)
ALIGN_MAX_SLIDE_CHARS = _env_int("ALIGN_MAX_SLIDE_CHARS", 1200, minimum=120)
ALIGN_MODEL_ALIAS = resolve_alignment_model_alias(os.getenv("ALIGN_MODEL"))
ALIGN_MODEL = resolve_alignment_model(os.getenv("ALIGN_MODEL"))

# Global semaphore caps total concurrent enrichment API calls across ALL running pipelines.
# Raise this (and ENRICH_MAX_WORKERS) together when upgrading to a higher API tier.
_ENRICH_GLOBAL_MAX_CONCURRENT = _env_int("ENRICH_GLOBAL_MAX_CONCURRENT", 3, minimum=1)
_global_enrich_semaphore = threading.Semaphore(_ENRICH_GLOBAL_MAX_CONCURRENT)

# Global semaphore caps total concurrent transcription API calls across ALL running pipelines.
_global_transcribe_semaphore = threading.Semaphore(TRANSCRIBE_GLOBAL_MAX_CONCURRENT)


def enrich_slide_notes(
    slide: dict,
    transcript_text: str,
    max_attempts: int = ENRICH_MAX_ATTEMPTS,
    log_callback=None,
    token_callback=None,
    *,
    return_metrics: bool = False,
    course_context: str | None = None,
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
        token_callback=token_callback,
        course_context=course_context,
    )
    if return_metrics:
        return enriched, metrics
    return enriched


def enrich_slides_batch_notes(
    slides_with_transcripts: list[tuple[dict, str]],
    max_attempts: int = ENRICH_MAX_ATTEMPTS,
    log_callback=None,
    token_callback=None,
    *,
    return_metrics: bool = False,
    course_context: str | None = None,
) -> list[dict] | tuple[list[dict], dict]:
    enriched, metrics = enrich_slides_batch_with_retry(
        enrichment_client,
        slides_with_transcripts,
        provider=ENRICH_PROVIDER,
        model=ENRICH_MODEL,
        max_output_tokens=ENRICH_MAX_OUTPUT_TOKENS,
        max_transcript_words=ENRICH_MAX_TRANSCRIPT_WORDS,
        max_attempts=max_attempts,
        log_usage=ENRICH_LOG_USAGE,
        log_callback=log_callback,
        token_callback=token_callback,
        course_context=course_context,
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


def _is_request_too_large_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 413:
        return True

    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 413:
        return True

    message = str(exc).lower()
    return (
        "error code: 413" in message
        or "request entity too large" in message
        or "request_too_large" in message
    )


def _is_transient_transcription_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code in (408, 409, 429, 500, 502, 503, 504):
        return True

    response = getattr(exc, "response", None)
    if response is not None:
        response_status = getattr(response, "status_code", None)
        if isinstance(response_status, int) and response_status in (408, 409, 429, 500, 502, 503, 504):
            return True

    message = str(exc).lower()
    return (
        "error code 524" in message
        or "a timeout occurred" in message
        or "timed out" in message
        or "temporarily unavailable" in message
        or "service unavailable" in message
        or "internal server error" in message
        or "rate limit" in message
        or "too many requests" in message
    )


def _retry_delay_seconds(attempt: int) -> float:
    base = max(1.0, TRANSCRIBE_RETRY_BASE_DELAY_SECONDS) * (2 ** (attempt - 1))
    return base * random.uniform(0.85, 1.15)


def _normalize_transcription_segments(raw_segments: list[dict]) -> list[dict]:
    def _value(seg: dict, key: str, default: float | str) -> float | str:
        if isinstance(seg, dict):
            return seg.get(key, default)
        if hasattr(seg, key):
            return getattr(seg, key)
        try:
            return seg[key]  # type: ignore[index]
        except Exception:
            return default

    normalized: list[dict] = []
    for seg in raw_segments:
        text = str(_value(seg, "text", "")).strip()
        if not text:
            continue
        normalized.append({
            "start": round(float(_value(seg, "start", 0.0)), 2),
            "end": round(float(_value(seg, "end", 0.0)), 2),
            "text": text,
        })
    return normalized


def _transcribe_mp3_file(mp3_path: Path) -> list[dict]:
    groq_client = Groq()
    with _global_transcribe_semaphore:
        with open(mp3_path, "rb") as f:
            result = groq_client.audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
    return _normalize_transcription_segments(list(result.segments))


def _transcribe_mp3_file_with_retries(
    mp3_path: Path,
    *,
    emit: ProgressEmitter | None = None,
    chunk_label: str | None = None,
) -> list[dict]:
    attempts = max(1, TRANSCRIBE_RETRY_ATTEMPTS)
    label = f" ({chunk_label})" if chunk_label else ""

    for attempt in range(1, attempts + 1):
        try:
            return _transcribe_mp3_file(mp3_path)
        except Exception as exc:
            if _is_request_too_large_error(exc):
                raise
            if not _is_transient_transcription_error(exc) or attempt >= attempts:
                raise

            delay_seconds = _retry_delay_seconds(attempt)
            message = (
                f"Transcription provider timeout{label}; retrying "
                f"({attempt + 1}/{attempts}) in {delay_seconds:.1f}s..."
            )
            print(f"⚠️ {message}", flush=True)
            _emit_progress(emit, "transcribe", message, 35)
            time.sleep(delay_seconds)


def _ffprobe_duration_seconds(path: Path) -> float:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = probe.stdout.strip()
    if not raw:
        raise RuntimeError(f"ffprobe returned an empty duration for {path}")
    duration = float(raw)
    if duration <= 0:
        raise RuntimeError(f"Invalid audio duration reported by ffprobe for {path}: {duration}")
    return duration


def _estimate_chunk_seconds(
    *,
    file_size_bytes: int,
    duration_seconds: float,
    force_split: bool,
) -> int:
    bytes_per_second = file_size_bytes / max(duration_seconds, 1.0)
    estimated = int(TRANSCRIBE_SAFE_BYTES / max(bytes_per_second, 1.0))
    estimated = max(TRANSCRIBE_MIN_CHUNK_SECONDS, estimated)

    if force_split and duration_seconds > TRANSCRIBE_MIN_CHUNK_SECONDS:
        half_duration = int(duration_seconds // 2)
        if half_duration > 0:
            estimated = min(estimated, max(TRANSCRIBE_MIN_CHUNK_SECONDS, half_duration))
    return estimated


def _transcribe_mp3_in_chunks(
    *,
    mp3_path: Path,
    duration_seconds: float,
    chunk_seconds: int,
    emit: ProgressEmitter | None = None,
) -> list[dict]:
    if chunk_seconds <= 0:
        raise RuntimeError("Chunk duration must be positive for chunked transcription")

    chunk_count = max(1, int((duration_seconds + chunk_seconds - 1) // chunk_seconds))
    chunk_tasks: list[tuple[int, float, Path]] = []

    with tempfile.TemporaryDirectory(prefix="transcribe-chunks-") as tmp_dir:
        for chunk_idx in range(chunk_count):
            chunk_start = float(chunk_idx * chunk_seconds)
            remaining = max(0.0, duration_seconds - chunk_start)
            if remaining <= 0.0:
                break

            chunk_duration = min(float(chunk_seconds), remaining)
            chunk_path = Path(tmp_dir) / f"chunk-{chunk_idx:04d}.mp3"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{chunk_start:.3f}",
                    "-t",
                    f"{chunk_duration:.3f}",
                    "-i",
                    str(mp3_path),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-b:a",
                    TRANSCRIBE_TARGET_BITRATE,
                    str(chunk_path),
                ],
                check=True,
                capture_output=True,
            )
            chunk_tasks.append((chunk_idx, chunk_start, chunk_path))

        if not chunk_tasks:
            return []

        chunk_total = len(chunk_tasks)

        def _transcribe_one_chunk(task: tuple[int, float, Path]) -> tuple[int, list[dict]]:
            chunk_idx, chunk_start, chunk_path = task
            chunk_segments = _transcribe_mp3_file_with_retries(
                chunk_path,
                emit=emit,
                chunk_label=f"chunk {chunk_idx + 1}/{chunk_total}",
            )
            adjusted_segments: list[dict] = []
            for seg in chunk_segments:
                start = round(chunk_start + float(seg["start"]), 2)
                end = round(chunk_start + float(seg["end"]), 2)
                text = str(seg["text"]).strip()
                if not text:
                    continue
                adjusted_segments.append({
                    "start": start,
                    "end": end,
                    "text": text,
                })
            return chunk_idx, adjusted_segments

        chunk_results: list[tuple[int, list[dict]]] = []
        done_count = 0

        def _emit_chunk_progress(done: int) -> None:
            progress_pct = 35 + int((done / max(chunk_total, 1)) * 12)
            _emit_progress(
                emit,
                "transcribe",
                f"Transcribing chunks... ({done}/{chunk_total})",
                progress_pct,
            )

        use_parallel = (
            TRANSCRIBE_PARALLEL_WORKERS > 1 and chunk_total >= TRANSCRIBE_PARALLEL_MIN_CHUNKS
        )
        if use_parallel:
            worker_count = min(TRANSCRIBE_PARALLEL_WORKERS, chunk_total)
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures = [pool.submit(_transcribe_one_chunk, task) for task in chunk_tasks]
                for future in as_completed(futures):
                    chunk_results.append(future.result())
                    done_count += 1
                    _emit_chunk_progress(done_count)
        else:
            for task in chunk_tasks:
                chunk_results.append(_transcribe_one_chunk(task))
                done_count += 1
                _emit_chunk_progress(done_count)

    ordered_segments: list[dict] = []
    for _, chunk_segments in sorted(chunk_results, key=lambda item: item[0]):
        ordered_segments.extend(chunk_segments)
    ordered_segments.sort(key=lambda seg: (float(seg["start"]), float(seg["end"])))
    return ordered_segments


def _transcribe_mp3_with_auto_chunking(
    *,
    mp3_path: Path,
    emit: ProgressEmitter | None = None,
) -> list[dict]:
    file_size_bytes = mp3_path.stat().st_size

    force_split = file_size_bytes > TRANSCRIBE_SAFE_BYTES
    if not force_split:
        try:
            return _transcribe_mp3_file_with_retries(mp3_path, emit=emit)
        except Exception as exc:
            if not _is_request_too_large_error(exc):
                raise
            force_split = True
            print(
                "⚠️ Transcription request exceeded provider payload size; retrying with chunked uploads...",
                flush=True,
            )

    duration_seconds = _ffprobe_duration_seconds(mp3_path)
    chunk_seconds = _estimate_chunk_seconds(
        file_size_bytes=file_size_bytes,
        duration_seconds=duration_seconds,
        force_split=force_split,
    )

    if chunk_seconds >= duration_seconds:
        # If a forced split would still produce a single chunk, force a safer two-chunk fallback.
        if force_split and duration_seconds >= 2 * TRANSCRIBE_MIN_CHUNK_SECONDS:
            chunk_seconds = int(duration_seconds // 2)
        else:
            chunk_seconds = int(duration_seconds)

    chunk_seconds = max(1, chunk_seconds)
    chunk_count = max(1, int((duration_seconds + chunk_seconds - 1) // chunk_seconds))
    print(
        f"✂️ Transcribing recording in {chunk_count} chunk(s) "
        f"(duration={duration_seconds:.1f}s, chunk_seconds={chunk_seconds})...",
        flush=True,
    )
    # chunk-level detail suppressed from UI; "Transcribing recording..." already shown

    try:
        return _transcribe_mp3_in_chunks(
            mp3_path=mp3_path,
            duration_seconds=duration_seconds,
            chunk_seconds=chunk_seconds,
            emit=emit,
        )
    except Exception as exc:
        if _is_request_too_large_error(exc):
            raise RuntimeError(
                "Recording is too large for the transcription provider limit, even after chunking. "
                "Try a shorter recording."
            ) from exc
        raise


def transcribe(audio_path: str, emit: ProgressEmitter | None = None) -> list[dict]:
    print("⏳ Compressing audio...", flush=True)
    _emit_progress(emit, "transcribe", "⏳ Compressing audio...", 28)
    mp3_path = Path(audio_path + ".tmp.mp3")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            audio_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            TRANSCRIBE_TARGET_BITRATE,
            str(mp3_path),
        ],
        check=True, capture_output=True,
    )
    print("☁️  Transcribing with Groq Whisper...", flush=True)
    _emit_progress(emit, "transcribe", "☁️ Transcribing recording...", 35)
    try:
        segments = _transcribe_mp3_with_auto_chunking(mp3_path=mp3_path, emit=emit)
    finally:
        mp3_path.unlink(missing_ok=True)
    print(f"✅ Transcription done — {len(segments)} segments", flush=True)
    _emit_progress(emit, "transcribe", f"Transcription complete: {len(segments)} segments.", 48)
    return segments


def _sanitize_alignment_boundaries(
    boundaries: list[dict],
    *,
    total_slides: int,
    total_segments: int,
) -> list[dict]:
    if total_slides <= 0:
        return []
    if total_segments <= 0:
        raise RuntimeError("Transcript was empty; cannot align slides.")

    parsed: dict[int, int] = {}
    for row in boundaries:
        try:
            slide = int(row.get("slide", 0))
            start_segment = int(row.get("start_segment", 0))
        except (TypeError, ValueError):
            continue
        if slide < 1 or slide > total_slides:
            continue
        parsed[slide] = start_segment

    parsed.setdefault(1, 0)
    sanitized: list[dict] = []
    previous = -1
    max_start = total_segments - 1

    for slide in range(1, total_slides + 1):
        candidate = parsed.get(slide, previous + 1)
        candidate = max(previous + 1, candidate)
        candidate = min(candidate, max_start)
        sanitized.append({"slide": slide, "start_segment": candidate})
        previous = candidate

    return sanitized


def align(
    slides: list[dict],
    transcript: list[dict],
    emit: ProgressEmitter | None = None,
) -> list[dict]:
    print(
        f"🔗 Aligning transcript to slides via Claude ({ALIGN_MODEL_ALIAS}:{ALIGN_MODEL})...",
        flush=True,
    )
    _emit_progress(emit, "align", "🔗 Aligning transcript to slides...", 55)
    prompt = build_prompt(
        slides,
        transcript,
        max_segments=ALIGN_MAX_TRANSCRIPT_SEGMENTS,
        max_segment_chars=ALIGN_MAX_SEGMENT_CHARS,
        max_slide_chars=ALIGN_MAX_SLIDE_CHARS,
    )
    try:
        message = alignment_client.messages.create(
            model=ALIGN_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        if not _is_request_too_large_error(exc):
            raise
        reduced_max_segments = max(200, ALIGN_MAX_TRANSCRIPT_SEGMENTS // 2)
        reduced_segment_chars = max(80, ALIGN_MAX_SEGMENT_CHARS // 2)
        reduced_slide_chars = max(300, ALIGN_MAX_SLIDE_CHARS // 2)
        print(
            "⚠️ Alignment request exceeded payload limit; retrying with a tighter prompt budget...",
            flush=True,
        )
        _emit_progress(
            emit,
            "align",
            "Large transcript detected. Retrying alignment with a compact prompt...",
            56,
        )
        prompt = build_prompt(
            slides,
            transcript,
            max_segments=reduced_max_segments,
            max_segment_chars=reduced_segment_chars,
            max_slide_chars=reduced_slide_chars,
        )
        message = alignment_client.messages.create(
            model=ALIGN_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    boundaries = parse_response(message.content[0].text)
    boundaries = _sanitize_alignment_boundaries(
        boundaries,
        total_slides=len(slides),
        total_segments=len(transcript),
    )

    result = []
    for i, b in enumerate(boundaries):
        start = b["start_segment"]
        end = (
            boundaries[i + 1]["start_segment"] - 1
            if i + 1 < len(boundaries)
            else len(transcript) - 1
        )
        end = max(start, end)
        result.append({"slide": b["slide"], "start_segment": start, "end_segment": end})

    # Cap the last slide's segment range so it doesn't absorb unbounded post-lecture audio.
    # Use 2× the average segments-per-slide as the ceiling.
    if result and len(result) > 1:
        avg_segments = sum(r["end_segment"] - r["start_segment"] + 1 for r in result) / len(result)
        cap = int(result[-1]["start_segment"] + max(avg_segments * 2, 30))
        cap = min(cap, len(transcript) - 1)
        if cap < result[-1]["end_segment"]:
            result[-1]["end_segment"] = cap
    print(f"✅ Alignment done — {len(result)} slides mapped", flush=True)
    _emit_progress(emit, "align", f"🔗 Alignment complete.", 65)
    return result


def enrich(
    slides: list[dict],
    transcript: list[dict],
    alignment: list[dict],
    emit: ProgressEmitter | None = None,
    on_slide_enriched: Callable[[int, dict], None] | None = None,
    course_context: str | None = None,
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
        f"batch_size={ENRICH_BATCH_SIZE}, max_output_tokens={ENRICH_MAX_OUTPUT_TOKENS}, "
        f"max_transcript_words={ENRICH_MAX_TRANSCRIPT_WORDS})...",
        flush=True,
    )
    _emit_progress(emit, "enrich", f"✨ Enriching {total} slides...", 70)
    slides_by_num = {s["slide"]: s for s in slides}

    def chunk_alignment_rows(rows: list[dict], size: int) -> list[list[dict]]:
        return [rows[idx:idx + size] for idx in range(0, len(rows), size)]

    def enrich_batch(batch: list[dict]) -> list[dict]:
        nonlocal done_count
        batch_inputs: list[tuple[dict, str]] = []
        slide_numbers: list[int] = []
        for a in batch:
            slide = slides_by_num[a["slide"]]
            text = " ".join(
                seg["text"].strip()
                for seg in transcript[a["start_segment"]: a["end_segment"] + 1]
            )
            batch_inputs.append((slide, text))
            slide_numbers.append(int(a["slide"]))
        with done_lock:
            in_progress_done = done_count
        pct_start = 70 + int((in_progress_done / total) * 20) if total > 0 else 70
        if len(slide_numbers) == 1:
            batch_label = str(slide_numbers[0])
        else:
            batch_label = f"{slide_numbers[0]}-{slide_numbers[-1]}"
        print(
            f"  ⏳ Enriching slides {batch_label} ({in_progress_done + 1}/{total})...",
            flush=True,
        )

        def slide_log(msg: str) -> None:
            _emit_progress(emit, "enrich", msg, pct_start)

        with _global_enrich_semaphore:
            enriched_batch, metrics = enrich_slides_batch_notes(
                batch_inputs,
                max_attempts=ENRICH_MAX_ATTEMPTS,
                log_callback=slide_log,
                token_callback=slide_log,
                return_metrics=True,
                course_context=course_context,
            )
        with metrics_lock:
            usage_totals["input_tokens"] += int(metrics.get("input_tokens", 0))
            usage_totals["output_tokens"] += int(metrics.get("output_tokens", 0))
            usage_totals["total_tokens"] += int(metrics.get("total_tokens", 0))
            usage_totals["retries"] += int(metrics.get("retries", 0))
            usage_totals["duration_ms"] += int(metrics.get("duration_ms", 0))
            usage_totals["fallbacks"] += int(metrics.get("fallbacks", 0))
            for reason, count in dict(metrics.get("failure_reason_counts", {})).items():
                if reason not in failure_reason_counts:
                    continue
                failure_reason_counts[reason] += int(count)

        enriched_by_slide = {int(entry["slide"]): entry for entry in enriched_batch}
        transcript_by_slide = {
            int(slide["slide"]): text
            for slide, text in batch_inputs
        }
        batch_results: list[dict] = []
        for a in batch:
            slide = slides_by_num[a["slide"]]
            enriched = enriched_by_slide.get(int(a["slide"]))
            if enriched is None:
                enriched = {
                    "slide": a["slide"],
                    **build_fallback_enrichment(slide, transcript_by_slide.get(int(a["slide"]), "")),
                }
            with done_lock:
                done_count += 1
                local_done = done_count
            print(f"  ✅ Slide {a['slide']} done ({local_done}/{total})", flush=True)
            if total > 0:
                pct = 70 + int((local_done / total) * 20)
            else:
                pct = 90
            _emit_progress(
                emit,
                "enrich",
                f"✅ Slide {a['slide']} done ({local_done}/{total})",
                pct,
            )
            result = {
                "slide": a["slide"],
                "original_text": slide["text"],
                "start_segment": a["start_segment"],
                "end_segment": a["end_segment"],
                "summary": enriched.get("summary", ""),
                "slide_content": enriched.get("slide_content", ""),
                "lecturer_additions": enriched.get("lecturer_additions", ""),
                "key_takeaways": enriched.get("key_takeaways", []),
            }
            if on_slide_enriched is not None:
                try:
                    on_slide_enriched(a["slide"], {
                        "slide": a["slide"],
                        "summary": result["summary"],
                        "slide_content": result["slide_content"],
                        "lecturer_additions": result["lecturer_additions"],
                        "key_takeaways": result["key_takeaways"],
                    })
                except Exception:
                    pass
            batch_results.append(result)
        return batch_results

    results: list[dict] = []
    batches = chunk_alignment_rows(alignment, ENRICH_BATCH_SIZE)
    with ThreadPoolExecutor(max_workers=ENRICH_MAX_WORKERS) as pool:
        futures = [pool.submit(enrich_batch, batch) for batch in batches]
        for future in as_completed(futures):
            results.extend(future.result())

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
    return results


def run_pipeline(
    pdf_path: str,
    audio_path: str,
    pptx_output_path: str,
    emit: ProgressEmitter | None = None,
    on_slides_parsed: Callable[[int], None] | None = None,
    on_slide_enriched: Callable[[int, dict], None] | None = None,
    on_pre_enrich: Callable[[list, list, list], None] | None = None,
    course_context: str | None = None,
) -> dict:
    # Step 1: Extract slides
    print("📄 Parsing slides from PDF...", flush=True)
    _emit_progress(emit, "parse_slides", "📄 Parsing slides...", 12)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        slides_tmp = f.name
    parse_slides(pdf_path, slides_tmp)
    with open(slides_tmp, encoding="utf-8") as f:
        slides = json.load(f)
    Path(slides_tmp).unlink(missing_ok=True)
    _emit_progress(emit, "parse_slides", f"📄 Extracted {len(slides)} slides.", 22)
    if on_slides_parsed is not None:
        try:
            on_slides_parsed(len(slides))
        except Exception:
            pass

    # Step 2: Transcribe audio
    transcript = transcribe(audio_path, emit=emit)

    # Step 3: Align
    alignment = align(slides, transcript, emit=emit)

    # Step 4: Enrich
    if on_pre_enrich is not None:
        try:
            on_pre_enrich(slides, transcript, alignment)
        except Exception:
            pass
    enhanced = enrich(slides, transcript, alignment, emit=emit, on_slide_enriched=on_slide_enriched, course_context=course_context)

    # Step 5: Generate PPTX
    _emit_progress(emit, "generate_pptx", "🎉 Generating presentation...", 93)
    generate_presentation_from_enhanced(pdf_path, enhanced, pptx_output_path)
    print("🎉 Pipeline complete!", flush=True)
    _emit_progress(emit, "generate_pptx", "🎉 Done!", 98)

    return {
        "slides": slides,
        "transcript": transcript,
        "alignment": alignment,
        "enhanced": enhanced,
        "download_url": f"/download/{Path(pptx_output_path).name}",
    }
