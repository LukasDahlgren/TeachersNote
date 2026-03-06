from typing import Callable

try:
    from pipeline_steps.progress import ProgressEmitter
except ImportError:  # pragma: no cover - package import fallback
    from backend.pipeline_steps.progress import ProgressEmitter


def sanitize_alignment_boundaries(
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


def align_transcript_to_slides(
    slides: list[dict],
    transcript: list[dict],
    *,
    emit: ProgressEmitter | None,
    emit_progress: Callable[[ProgressEmitter | None, str, str, int], None],
    alignment_client,
    align_model_alias: str,
    align_model: str,
    max_transcript_segments: int,
    max_segment_chars: int,
    max_slide_chars: int,
    is_request_too_large_error: Callable[[Exception], bool],
    build_prompt: Callable[..., str] | None = None,
    parse_response: Callable[[str], list[dict]] | None = None,
) -> list[dict]:
    if build_prompt is None or parse_response is None:
        from scripts.align import build_prompt as default_build_prompt, parse_response as default_parse_response

        build_prompt = build_prompt or default_build_prompt
        parse_response = parse_response or default_parse_response

    print(
        f"🔗 Aligning transcript to slides via Claude ({align_model_alias}:{align_model})...",
        flush=True,
    )
    emit_progress(emit, "align", "🔗 Aligning transcript to slides...", 55)
    prompt = build_prompt(
        slides,
        transcript,
        max_segments=max_transcript_segments,
        max_segment_chars=max_segment_chars,
        max_slide_chars=max_slide_chars,
    )
    try:
        message = alignment_client.messages.create(
            model=align_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        if not is_request_too_large_error(exc):
            raise
        reduced_max_segments = max(200, max_transcript_segments // 2)
        reduced_segment_chars = max(80, max_segment_chars // 2)
        reduced_slide_chars = max(300, max_slide_chars // 2)
        print(
            "⚠️ Alignment request exceeded payload limit; retrying with a tighter prompt budget...",
            flush=True,
        )
        emit_progress(
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
            model=align_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    boundaries = parse_response(message.content[0].text)
    boundaries = sanitize_alignment_boundaries(
        boundaries,
        total_slides=len(slides),
        total_segments=len(transcript),
    )

    result = []
    for idx, boundary in enumerate(boundaries):
        start = boundary["start_segment"]
        end = (
            boundaries[idx + 1]["start_segment"] - 1
            if idx + 1 < len(boundaries)
            else len(transcript) - 1
        )
        end = max(start, end)
        result.append({"slide": boundary["slide"], "start_segment": start, "end_segment": end})

    if result and len(result) > 1:
        avg_segments = sum(item["end_segment"] - item["start_segment"] + 1 for item in result) / len(result)
        cap = int(result[-1]["start_segment"] + max(avg_segments * 2, 30))
        cap = min(cap, len(transcript) - 1)
        if cap < result[-1]["end_segment"]:
            result[-1]["end_segment"] = cap
    print(f"✅ Alignment done — {len(result)} slides mapped", flush=True)
    emit_progress(emit, "align", "🔗 Alignment complete.", 65)
    return result
