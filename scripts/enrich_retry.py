import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

try:
    from .enrich_client import _add_usage, _is_connection_error, _is_rate_limit_error, _safe_int
    from .enrich_parsing import (
        _collapse_whitespace,
        _format_lecturer_additions,
        _normalize_slide_text,
        _pick_first,
        _sentence_chunks,
        is_enriched_payload_invalid,
        normalize_enriched_payload,
        parse_enrichment_batch_response,
        parse_enrichment_response,
    )
    from .enrich_policy import _clean_lines_for_relevance, enforce_relevance_policy
    from .enrich_prompt import (
        BATCH_SYSTEM_PROMPT,
        STRICT_BATCH_SYSTEM_PROMPT,
        STRICT_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
        build_batch_user_prompt,
        build_user_prompt,
        truncate_transcript_for_prompt,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from enrich_client import _add_usage, _is_connection_error, _is_rate_limit_error, _safe_int
    from enrich_parsing import (
        _collapse_whitespace,
        _format_lecturer_additions,
        _normalize_slide_text,
        _pick_first,
        _sentence_chunks,
        is_enriched_payload_invalid,
        normalize_enriched_payload,
        parse_enrichment_batch_response,
        parse_enrichment_response,
    )
    from enrich_policy import _clean_lines_for_relevance, enforce_relevance_policy
    from enrich_prompt import (
        BATCH_SYSTEM_PROMPT,
        STRICT_BATCH_SYSTEM_PROMPT,
        STRICT_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
        build_batch_user_prompt,
        build_user_prompt,
        truncate_transcript_for_prompt,
    )


class EnrichmentResponseError(ValueError):
    def __init__(
        self,
        message: str,
        usage: dict[str, int] | None = None,
        *,
        reason: str = "invalid_payload",
    ):
        super().__init__(message)
        self.usage = usage or {}
        self.reason = reason


def build_fallback_enrichment(slide: dict, transcript_text: str) -> dict:
    slide_text = _normalize_slide_text(str(slide.get("text", "")))
    transcript_compact = _collapse_whitespace(transcript_text)
    slide_number = slide.get("slide", "?")

    summary_candidates = _sentence_chunks(transcript_compact, 1) or _sentence_chunks(slide_text, 1)
    summary = summary_candidates[0] if summary_candidates else f"Slide {slide_number} sammanfattar forelasningens innehall."

    slide_content = slide_text or "Slideinnehall kunde inte extraheras automatiskt."
    lecturer_additions = _format_lecturer_additions(transcript_compact) if transcript_compact else ""

    takeaways = _sentence_chunks(transcript_compact, 3)
    if not takeaways:
        takeaways = _clean_lines_for_relevance(slide_text)[:3]
    if not takeaways:
        takeaways = [f"Se slide {slide_number} och transkriptet for fullstandig kontext."]

    fallback = {
        "summary": summary,
        "slide_content": slide_content,
        "lecturer_additions": lecturer_additions,
        "key_takeaways": takeaways,
    }
    filtered = enforce_relevance_policy(fallback, slide_text)
    if not is_enriched_payload_invalid(filtered):
        return filtered
    return fallback


def enrich_slide_impl(
    client: Any,
    slide: dict,
    transcript_text: str,
    provider: str,
    model: str,
    max_output_tokens: int,
    *,
    call_enrichment_model_fn: Callable[..., tuple[str, dict[str, int]]],
    system_prompt: str = SYSTEM_PROMPT,
    token_callback: Callable[[str], None] | None = None,
    course_context: str | None = None,
) -> tuple[dict, dict[str, int]]:
    user_prompt = build_user_prompt(slide, transcript_text, course_context=course_context)
    raw, usage = call_enrichment_model_fn(
        client,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=max_output_tokens,
        token_callback=token_callback,
    )
    parsed = parse_enrichment_response(raw)
    if parsed is None:
        raise EnrichmentResponseError(
            f"No JSON object found in enrichment response: {raw[:240]}",
            usage=usage,
            reason="no_json",
        )

    normalized = normalize_enriched_payload(parsed)
    filtered = enforce_relevance_policy(normalized, str(slide.get("text", "")))
    if is_enriched_payload_invalid(filtered):
        raise EnrichmentResponseError(
            "Enrichment response parsed but all canonical fields were empty",
            usage=usage,
            reason="empty_payload",
        )
    return filtered, usage


def _coerce_slide_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _batch_slide_label(slides_with_transcripts: list[tuple[dict, str]]) -> str:
    slide_numbers = [
        slide_num
        for slide_num in (_coerce_slide_number(slide.get("slide")) for slide, _ in slides_with_transcripts)
        if slide_num is not None
    ]
    if not slide_numbers:
        return "?"
    if len(slide_numbers) == 1:
        return str(slide_numbers[0])
    return f"{slide_numbers[0]}-{slide_numbers[-1]}"


def _empty_failure_reason_counts() -> dict[str, int]:
    return {
        "truncated_json": 0,
        "empty_payload": 0,
        "connection_error": 0,
        "other_error": 0,
    }


def _record_fallback_reason(counts: dict[str, int], reason: Any) -> None:
    key = str(reason or "other_error")
    if key not in counts:
        key = "other_error"
    counts[key] += 1


def enrich_slides_batch_impl(
    client: Any,
    slides_with_transcripts: list[tuple[dict, str]],
    *,
    provider: str,
    model: str,
    max_output_tokens: int,
    call_enrichment_model_fn: Callable[..., tuple[str, dict[str, int]]],
    system_prompt: str = BATCH_SYSTEM_PROMPT,
    token_callback: Callable[[str], None] | None = None,
    course_context: str | None = None,
) -> tuple[dict[int, dict], list[tuple[dict, str]], dict[str, int]]:
    user_prompt = build_batch_user_prompt(slides_with_transcripts, course_context=course_context)
    raw, usage = call_enrichment_model_fn(
        client,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=max_output_tokens,
        token_callback=token_callback,
    )
    parsed_items = parse_enrichment_batch_response(raw)
    if parsed_items is None:
        raise EnrichmentResponseError(
            f"No JSON array found in batch enrichment response: {raw[:240]}",
            usage=usage,
            reason="no_json",
        )

    parsed_by_slide: dict[int, dict] = {}
    for item in parsed_items:
        slide_num = _coerce_slide_number(
            _pick_first(item, ("slide", "slide_number", "slideNumber")),
        )
        if slide_num is None or slide_num in parsed_by_slide:
            continue
        parsed_by_slide[slide_num] = item

    resolved: dict[int, dict] = {}
    unresolved: list[tuple[dict, str]] = []
    for slide, transcript_text in slides_with_transcripts:
        slide_num = _coerce_slide_number(slide.get("slide"))
        if slide_num is None:
            unresolved.append((slide, transcript_text))
            continue
        payload = parsed_by_slide.get(slide_num)
        if payload is None:
            unresolved.append((slide, transcript_text))
            continue
        normalized = normalize_enriched_payload(payload)
        filtered = enforce_relevance_policy(normalized, str(slide.get("text", "")))
        if is_enriched_payload_invalid(filtered):
            unresolved.append((slide, transcript_text))
            continue
        resolved[slide_num] = filtered

    if not resolved:
        raise EnrichmentResponseError(
            "Batch enrichment response parsed but all canonical fields were empty",
            usage=usage,
            reason="empty_payload",
        )
    return resolved, unresolved, usage


_HEARTBEAT_INTERVAL = 10


def _sleep_with_heartbeat(
    total_seconds: int,
    *,
    slide_num: Any,
    log_callback: Callable[[str], None] | None,
) -> None:
    remaining = total_seconds
    while remaining > 0:
        chunk = min(_HEARTBEAT_INTERVAL, remaining)
        time.sleep(chunk)
        remaining -= chunk
        if remaining > 0 and log_callback:
            log_callback(f"⏳ Slide {slide_num}: rate-limited, ~{remaining}s remaining...")


def enrich_slides_batch_with_retry_impl(
    client: Any,
    slides_with_transcripts: list[tuple[dict, str]],
    *,
    provider: str,
    model: str,
    call_enrichment_model_fn: Callable[..., tuple[str, dict[str, int]]],
    enrich_slide_with_retry_fn: Callable[..., tuple[dict, dict[str, Any]]],
    max_output_tokens: int,
    max_transcript_words: int,
    max_attempts: int,
    log_usage: bool,
    log_callback: Callable[[str], None] | None = None,
    token_callback: Callable[[str], None] | None = None,
    course_context: str | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    if not slides_with_transcripts:
        empty_metrics = {
            "provider": provider,
            "model": model,
            "attempts": 0,
            "retries": 0,
            "fallbacks": 0,
            "duration_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "raw_transcript_words": 0,
            "prompt_transcript_words": 0,
            "failure_reason_counts": _empty_failure_reason_counts(),
            "batch_size": 0,
        }
        return [], empty_metrics

    if len(slides_with_transcripts) == 1:
        slide, transcript_text = slides_with_transcripts[0]
        enriched, metrics = enrich_slide_with_retry_fn(
            client,
            slide,
            transcript_text,
            provider=provider,
            model=model,
            max_output_tokens=max_output_tokens,
            max_transcript_words=max_transcript_words,
            max_attempts=max_attempts,
            log_usage=log_usage,
            log_callback=log_callback,
            token_callback=token_callback,
            course_context=course_context,
        )
        failure_reason_counts = _empty_failure_reason_counts()
        if metrics.get("fallback_used"):
            _record_fallback_reason(failure_reason_counts, metrics.get("failure_reason"))
        slide_num = _coerce_slide_number(slide.get("slide")) or 0
        adapted_metrics = {
            "provider": provider,
            "model": model,
            "attempts": int(metrics.get("attempts", 0)),
            "retries": int(metrics.get("retries", 0)),
            "fallbacks": 1 if metrics.get("fallback_used") else 0,
            "duration_ms": int(metrics.get("duration_ms", 0)),
            "input_tokens": int(metrics.get("input_tokens", 0)),
            "output_tokens": int(metrics.get("output_tokens", 0)),
            "total_tokens": int(metrics.get("total_tokens", 0)),
            "raw_transcript_words": int(metrics.get("raw_transcript_words", 0)),
            "prompt_transcript_words": int(metrics.get("prompt_transcript_words", 0)),
            "failure_reason_counts": failure_reason_counts,
            "batch_size": 1,
        }
        return [{"slide": slide_num, **enriched}], adapted_metrics

    usage_total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    raw_word_count = sum(len(transcript_text.split()) for _, transcript_text in slides_with_transcripts)
    prompt_batch = [
        (slide, truncate_transcript_for_prompt(transcript_text, max_transcript_words))
        for slide, transcript_text in slides_with_transcripts
    ]
    prompt_word_count = sum(len(prompt_text.split()) for _, prompt_text in prompt_batch)
    started = time.perf_counter()
    attempts = 0
    batch_retries = 0
    truncation_retry_used = False
    next_attempt_tokens: int | None = None
    batch_label = _batch_slide_label(slides_with_transcripts)
    batch_resolved: dict[int, dict] = {}
    unresolved = list(slides_with_transcripts)
    last_error: Exception | None = None

    batch_count = len(prompt_batch)

    for attempt in range(max_attempts):
        attempts = attempt + 1
        current_max_output_tokens = next_attempt_tokens or max_output_tokens
        next_attempt_tokens = None
        batch_max_output_tokens = current_max_output_tokens * batch_count
        try:
            batch_resolved, unresolved, usage = enrich_slides_batch_impl(
                client,
                prompt_batch,
                provider=provider,
                model=model,
                max_output_tokens=batch_max_output_tokens,
                call_enrichment_model_fn=call_enrichment_model_fn,
                system_prompt=STRICT_BATCH_SYSTEM_PROMPT,
                token_callback=token_callback,
                course_context=course_context,
            )
            _add_usage(usage_total, usage)
            break
        except EnrichmentResponseError as exc:
            last_error = exc
            _add_usage(usage_total, exc.usage)
            attempt_output_tokens = _safe_int(exc.usage.get("output_tokens", 0))
            is_truncated_json = (
                exc.reason == "no_json"
                and attempt_output_tokens >= batch_max_output_tokens
            )
            if is_truncated_json:
                if not truncation_retry_used and attempt < max_attempts - 1:
                    truncation_retry_used = True
                    expanded_per_slide = min(max_output_tokens * 2, 1200)
                    if expanded_per_slide > current_max_output_tokens:
                        next_attempt_tokens = expanded_per_slide
                        batch_retries += 1
                        msg = (
                            f"⚠️ Truncated JSON detected on slides {batch_label} "
                            f"(attempt {attempt + 1}/{max_attempts}), retrying with max_output_tokens={expanded_per_slide * batch_count}..."
                        )
                        print(f"  {msg}", flush=True)
                        if log_callback:
                            log_callback(msg)
                        continue
            if attempt < max_attempts - 1:
                batch_retries += 1
                wait = min(8, attempt + 1)
                msg = (
                    f"⚠️ Batch enrichment error on slides {batch_label} [{exc.reason}] "
                    f"(attempt {attempt + 1}/{max_attempts}), retrying in {wait}s..."
                )
                print(f"  {msg}", flush=True)
                if log_callback:
                    log_callback(msg)
                time.sleep(wait)
            else:
                break
        except Exception as exc:
            last_error = exc
            if _is_rate_limit_error(exc):
                if attempt < max_attempts - 1:
                    batch_retries += 1
                wait = min(30 * (attempt + 1), 120)
                msg = f"⏳ Rate limited on slides {batch_label}, waiting {wait}s..."
                print(f"  {msg}", flush=True)
                if log_callback:
                    log_callback(msg)
                _sleep_with_heartbeat(wait, slide_num=batch_label, log_callback=log_callback)
            else:
                if attempt < max_attempts - 1:
                    batch_retries += 1
                    wait = min(8, attempt + 1)
                    msg = (
                        f"⚠️ Batch enrichment exception on slides {batch_label} "
                        f"[{type(exc).__name__}: {exc}] (attempt {attempt + 1}/{max_attempts}), retrying in {wait}s..."
                    )
                    print(f"  {msg}", flush=True)
                    if log_callback:
                        log_callback(msg)
                    time.sleep(wait)
                else:
                    break

    slide_results: dict[int, dict] = dict(batch_resolved)
    failure_reason_counts = _empty_failure_reason_counts()
    fallback_count = 0

    unresolved_slide_numbers = [
        slide_num
        for slide_num in (
            _coerce_slide_number(slide.get("slide"))
            for slide, _ in unresolved
        )
        if slide_num is not None
    ]

    if unresolved:
        if batch_resolved:
            missing = ", ".join(str(slide_num) for slide_num in unresolved_slide_numbers) or "?"
            msg = f"⚠️ Batch response incomplete for slides {missing}; retrying those slides individually..."
        else:
            msg = f"⚠️ Falling back to individual enrichment for slides {batch_label} after repeated batch errors"
            if last_error is not None:
                msg = f"{msg}: {last_error}"
        print(f"  {msg}", flush=True)
        if log_callback:
            log_callback(msg)

    for slide, transcript_text in unresolved:
        enriched, metrics = enrich_slide_with_retry_fn(
            client,
            slide,
            transcript_text,
            provider=provider,
            model=model,
            max_output_tokens=max_output_tokens,
            max_transcript_words=max_transcript_words,
            max_attempts=max_attempts,
            log_usage=log_usage,
            log_callback=log_callback,
            token_callback=token_callback,
            course_context=course_context,
        )
        slide_num = _coerce_slide_number(slide.get("slide"))
        if slide_num is not None:
            slide_results[slide_num] = enriched
        usage_total["input_tokens"] += int(metrics.get("input_tokens", 0))
        usage_total["output_tokens"] += int(metrics.get("output_tokens", 0))
        usage_total["total_tokens"] += int(metrics.get("total_tokens", 0))
        batch_retries += int(metrics.get("retries", 0))
        if metrics.get("fallback_used"):
            fallback_count += 1
            _record_fallback_reason(failure_reason_counts, metrics.get("failure_reason"))

    ordered_results: list[dict] = []
    for slide, transcript_text in slides_with_transcripts:
        slide_num = _coerce_slide_number(slide.get("slide"))
        if slide_num is None:
            continue
        enriched = slide_results.get(slide_num)
        if enriched is None:
            enriched = build_fallback_enrichment(slide, transcript_text)
            fallback_count += 1
            _record_fallback_reason(failure_reason_counts, "other_error")
        ordered_results.append({"slide": slide_num, **enriched})

    duration_ms = int((time.perf_counter() - started) * 1000)
    metrics = {
        "provider": provider,
        "model": model,
        "attempts": attempts,
        "retries": batch_retries,
        "fallbacks": fallback_count,
        "duration_ms": duration_ms,
        "input_tokens": usage_total["input_tokens"],
        "output_tokens": usage_total["output_tokens"],
        "total_tokens": usage_total["total_tokens"],
        "raw_transcript_words": raw_word_count,
        "prompt_transcript_words": prompt_word_count,
        "failure_reason_counts": failure_reason_counts,
        "batch_size": len(slides_with_transcripts),
    }
    if log_usage:
        msg = (
            f"📊 Slides {batch_label} usage: provider={provider} model={model} attempts={metrics['attempts']} "
            f"retries={metrics['retries']} input_tokens={metrics['input_tokens']} "
            f"output_tokens={metrics['output_tokens']} total_tokens={metrics['total_tokens']} "
            f"duration_ms={metrics['duration_ms']} fallback_slides={metrics['fallbacks']}"
        )
        print(f"  {msg}", flush=True)
        if log_callback:
            log_callback(msg)
    return ordered_results, metrics


def enrich_slide_with_retry_impl(
    client: Any,
    slide: dict,
    transcript_text: str,
    *,
    provider: str,
    model: str,
    call_enrichment_model_fn: Callable[..., tuple[str, dict[str, int]]],
    max_output_tokens: int,
    max_transcript_words: int,
    max_attempts: int,
    log_usage: bool,
    log_callback: Callable[[str], None] | None = None,
    token_callback: Callable[[str], None] | None = None,
    course_context: str | None = None,
) -> tuple[dict, dict[str, Any]]:
    last_error: Exception | None = None
    attempts = 0
    usage_total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    raw_word_count = len(transcript_text.split())
    prompt_transcript_text = truncate_transcript_for_prompt(transcript_text, max_transcript_words)
    prompt_word_count = len(prompt_transcript_text.split())
    started = time.perf_counter()
    slide_num = slide.get("slide", "?")
    truncation_retry_used = False
    next_attempt_tokens: int | None = None
    failure_reason = "none"

    for attempt in range(max_attempts):
        attempts = attempt + 1
        current_max_output_tokens = next_attempt_tokens or max_output_tokens
        next_attempt_tokens = None
        try:
            enriched, usage = enrich_slide_impl(
                client,
                slide,
                prompt_transcript_text,
                provider,
                model,
                current_max_output_tokens,
                call_enrichment_model_fn=call_enrichment_model_fn,
                system_prompt=STRICT_SYSTEM_PROMPT,
                token_callback=token_callback,
                course_context=course_context,
            )
            _add_usage(usage_total, usage)

            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics = {
                "provider": provider,
                "model": model,
                "attempts": attempts,
                "retries": max(0, attempts - 1),
                "fallback_used": False,
                "duration_ms": duration_ms,
                "input_tokens": usage_total["input_tokens"],
                "output_tokens": usage_total["output_tokens"],
                "total_tokens": usage_total["total_tokens"],
                "raw_transcript_words": raw_word_count,
                "prompt_transcript_words": prompt_word_count,
                "failure_reason": "none",
            }
            if log_usage:
                msg = (
                    f"📊 Slide {slide_num} usage: provider={provider} model={model} attempts={metrics['attempts']} "
                    f"retries={metrics['retries']} input_tokens={metrics['input_tokens']} "
                    f"output_tokens={metrics['output_tokens']} total_tokens={metrics['total_tokens']} "
                    f"duration_ms={metrics['duration_ms']} fallback={metrics['fallback_used']}"
                )
                print(f"  {msg}", flush=True)
                if log_callback:
                    log_callback(msg)
            return enriched, metrics
        except EnrichmentResponseError as exc:
            last_error = exc
            _add_usage(usage_total, exc.usage)
            failure_reason = exc.reason
            attempt_output_tokens = _safe_int(exc.usage.get("output_tokens", 0))
            is_truncated_json = (
                exc.reason == "no_json"
                and attempt_output_tokens >= current_max_output_tokens
            )

            if is_truncated_json:
                failure_reason = "truncated_json"
                if not truncation_retry_used and attempt < max_attempts - 1:
                    truncation_retry_used = True
                    expanded = min(max_output_tokens * 2, 1200)
                    if expanded > current_max_output_tokens:
                        next_attempt_tokens = expanded
                        msg = (
                            f"⚠️ Truncated JSON detected on slide {slide_num} "
                            f"(attempt {attempt + 1}/{max_attempts}), retrying with max_output_tokens={expanded}..."
                        )
                        print(f"  {msg}", flush=True)
                        if log_callback:
                            log_callback(msg)
                        continue

            if attempt < max_attempts - 1:
                wait = min(8, attempt + 1)
                msg = (
                    f"⚠️ Enrichment error on slide {slide_num} [{exc.reason}] "
                    f"(attempt {attempt + 1}/{max_attempts}), retrying in {wait}s..."
                )
                print(f"  {msg}", flush=True)
                if log_callback:
                    log_callback(msg)
                time.sleep(wait)
            else:
                break
        except Exception as exc:
            last_error = exc
            failure_reason = "connection_error" if _is_connection_error(exc) else "other_error"
            if _is_rate_limit_error(exc):
                wait = min(30 * (attempt + 1), 120)
                msg = f"⏳ Rate limited on slide {slide_num}, waiting {wait}s..."
                print(f"  {msg}", flush=True)
                if log_callback:
                    log_callback(msg)
                _sleep_with_heartbeat(wait, slide_num=slide_num, log_callback=log_callback)
            else:
                if attempt < max_attempts - 1:
                    wait = min(8, attempt + 1)
                    msg = (
                        f"⚠️ Enrichment exception on slide {slide_num} [{type(exc).__name__}: {exc}] "
                        f"(attempt {attempt + 1}/{max_attempts}), retrying in {wait}s..."
                    )
                    print(f"  {msg}", flush=True)
                    if log_callback:
                        log_callback(msg)
                    time.sleep(wait)
                else:
                    break

    msg = f"⚠️ Falling back to deterministic notes for slide {slide_num} after repeated errors"
    print(f"  {msg}: {last_error}", flush=True)
    if log_callback:
        log_callback(msg)
    fallback = build_fallback_enrichment(slide, transcript_text)
    duration_ms = int((time.perf_counter() - started) * 1000)
    if failure_reason not in {"truncated_json", "empty_payload", "connection_error", "other_error"}:
        failure_reason = "other_error"
    metrics = {
        "provider": provider,
        "model": model,
        "attempts": max(1, attempts),
        "retries": max(0, max(1, attempts) - 1),
        "fallback_used": True,
        "duration_ms": duration_ms,
        "input_tokens": usage_total["input_tokens"],
        "output_tokens": usage_total["output_tokens"],
        "total_tokens": usage_total["total_tokens"],
        "raw_transcript_words": raw_word_count,
        "prompt_transcript_words": prompt_word_count,
        "failure_reason": failure_reason,
    }
    if log_usage:
        usage_msg = (
            f"📊 Slide {slide_num} usage: provider={provider} model={model} attempts={metrics['attempts']} "
            f"retries={metrics['retries']} input_tokens={metrics['input_tokens']} "
            f"output_tokens={metrics['output_tokens']} total_tokens={metrics['total_tokens']} "
            f"duration_ms={metrics['duration_ms']} fallback={metrics['fallback_used']} "
            f"failure_reason={metrics['failure_reason']}"
        )
        print(f"  {usage_msg}", flush=True)
        if log_callback:
            log_callback(usage_msg)
    return fallback, metrics


def enrich_impl(
    slides_path: str,
    aligned_path: str,
    transcript_path: str,
    output_path: str,
    *,
    resolve_enrichment_provider_fn: Callable[[str | None], str],
    default_enrichment_model_fn: Callable[[str], str],
    create_enrichment_client_fn: Callable[[str | None], Any],
    enrich_slides_batch_with_retry_fn: Callable[..., tuple[list[dict], dict[str, Any]]],
    default_enrich_model_override: str,
    default_enrich_batch_size: int,
    max_workers: int,
    max_attempts: int,
    max_transcript_words: int,
    max_output_tokens: int,
    provider: str | None = None,
    model: str | None = None,
    log_usage: bool = True,
) -> None:
    with open(slides_path, encoding="utf-8") as f:
        slides = json.load(f)
    with open(aligned_path, encoding="utf-8") as f:
        aligned = json.load(f)
    with open(transcript_path, encoding="utf-8") as f:
        segments = json.load(f)

    slides_by_num = {slide["slide"]: slide for slide in slides}

    try:
        with open(output_path, encoding="utf-8") as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = []

    already_done = {entry["slide"] for entry in existing}
    results = list(existing)
    results_lock = threading.Lock()

    pending = [entry for entry in aligned if entry["slide"] not in already_done]
    total = len(aligned)

    if already_done:
        print(f"Resuming: {len(already_done)}/{total} slides already done, {len(pending)} remaining")

    resolved_provider = resolve_enrichment_provider_fn(provider)
    resolved_model = (
        model.strip()
        if model and model.strip()
        else (default_enrich_model_override or default_enrichment_model_fn(resolved_provider))
    )
    enrich_client = create_enrichment_client_fn(resolved_provider)
    batch_size = default_enrich_batch_size

    def _chunked(items: list[dict], size: int) -> list[list[dict]]:
        return [items[idx:idx + size] for idx in range(0, len(items), size)]

    def process(batch: list[dict]) -> None:
        batch_inputs: list[tuple[dict, str]] = []
        for entry in batch:
            slide = slides_by_num[entry["slide"]]
            transcript_segs = segments[entry["start_segment"]: entry["end_segment"] + 1]
            transcript_text = " ".join(segment["text"].strip() for segment in transcript_segs)
            batch_inputs.append((slide, transcript_text))

        enriched_batch, _metrics = enrich_slides_batch_with_retry_fn(
            enrich_client,
            batch_inputs,
            provider=resolved_provider,
            model=resolved_model,
            max_output_tokens=max_output_tokens,
            max_transcript_words=max_transcript_words,
            max_attempts=max_attempts,
            log_usage=log_usage,
        )
        enriched_by_slide = {entry["slide"]: entry for entry in enriched_batch}
        transcript_by_slide = {
            int(slide["slide"]): transcript_text
            for slide, transcript_text in batch_inputs
        }
        batch_entries: list[dict] = []
        for entry in batch:
            slide = slides_by_num[entry["slide"]]
            enriched = enriched_by_slide.get(entry["slide"]) or {
                "slide": entry["slide"],
                **build_fallback_enrichment(slide, transcript_by_slide.get(entry["slide"], "")),
            }
            batch_entries.append({
                "slide": entry["slide"],
                "original_text": slide["text"],
                "start_segment": entry["start_segment"],
                "end_segment": entry["end_segment"],
                "summary": enriched.get("summary", ""),
                "slide_content": enriched.get("slide_content", ""),
                "lecturer_additions": enriched.get("lecturer_additions", ""),
                "key_takeaways": enriched.get("key_takeaways", []),
            })

        with results_lock:
            results.extend(batch_entries)
            total_done = len(results)

        start_done = total_done - len(batch_entries)
        for offset, entry in enumerate(batch, start=1):
            print(
                f"  Slide {entry['slide']}/{total} done ({start_done + offset}/{total} total)",
                flush=True,
            )

    batches = _chunked(pending, batch_size)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(process, batch) for batch in batches]
        for future in as_completed(futures):
            future.result()

    sorted_results = sorted(results, key=lambda entry: entry["slide"])
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sorted_results, f, ensure_ascii=False, indent=2)

    print(f"\nEnriched {len(results)} slides → {output_path}")


__all__ = [
    "EnrichmentResponseError",
    "_HEARTBEAT_INTERVAL",
    "_batch_slide_label",
    "_coerce_slide_number",
    "_empty_failure_reason_counts",
    "_record_fallback_reason",
    "_sleep_with_heartbeat",
    "build_fallback_enrichment",
    "enrich_impl",
    "enrich_slide_impl",
    "enrich_slide_with_retry_impl",
    "enrich_slides_batch_impl",
    "enrich_slides_batch_with_retry_impl",
]
