import argparse
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised only in minimal local envs
    anthropic = None  # type: ignore[assignment]

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised only in minimal local envs
    OpenAI = None  # type: ignore[assignment]


def _env_truthy(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw.strip())
    except ValueError:
        return default
    return max(minimum, parsed)


DEFAULT_ENRICH_PROVIDER = os.getenv("ENRICH_PROVIDER", "anthropic").strip().lower() or "anthropic"
DEFAULT_ENRICH_MODEL_OVERRIDE = os.getenv("ENRICH_MODEL", "").strip()
DEFAULT_ENRICH_MODEL_ANTHROPIC = os.getenv("ENRICH_MODEL_ANTHROPIC", "claude-haiku-4-5").strip() or "claude-haiku-4-5"
DEFAULT_ENRICH_MODEL_GROQ = os.getenv("ENRICH_MODEL_GROQ", "openai/gpt-oss-20b").strip() or "openai/gpt-oss-20b"
DEFAULT_ENRICH_MAX_WORKERS = _env_int("ENRICH_MAX_WORKERS", 4, minimum=1)
DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS = _env_int("ENRICH_MAX_TRANSCRIPT_WORDS", 700, minimum=1)
DEFAULT_ENRICH_MAX_OUTPUT_TOKENS = _env_int("ENRICH_MAX_OUTPUT_TOKENS", 320, minimum=64)
DEFAULT_ENRICH_MAX_ATTEMPTS = _env_int("ENRICH_MAX_ATTEMPTS", 4, minimum=1)
DEFAULT_ENRICH_LOG_USAGE = _env_truthy("ENRICH_LOG_USAGE", True)

SUPPORTED_ENRICH_PROVIDERS = {"anthropic", "groq"}

SYSTEM_PROMPT = """Du är assistent som hjälper studenter att förstå föreläsningsinnehåll.
Du får en föreläsningsbild (slide) och en transkription av vad föreläsaren sade under den bilden.
Din uppgift är att skapa berikade anteckningar på svenska som fångar:
1. Vad bilden visar (sammanfattning av slidens text)
2. Viktiga saker föreläsaren nämnde som INTE framgår av bilden
3. Exempel, förklaringar och anekdoter som föreläsaren gav
4. Praktiska råd eller varningar föreläsaren lyfte fram

Svara ALLTID med ett JSON-objekt (inga kodblock, bara ren JSON) med dessa fält:
{
  "summary": "Exakt en mening som sammanfattar slidens ämne",
  "slide_content": "3-5 punktlistor där varje rad börjar med '- '",
  "lecturer_additions": "Max 6 punktlistor där varje rad börjar med '- ' och innehåller allt relevant från föreläsaren utöver bilden",
  "key_takeaways": ["exakt tre takeaways"]
}"""

STRICT_SYSTEM_PROMPT = """Du måste svara med ENDAST ett giltigt JSON-objekt.
Ingen inledande text, inga kodblock, inga extra nycklar.
Använd exakt dessa nycklar:
- summary (string)
- slide_content (string med 3-5 punktlistor där varje rad börjar med '- ')
- lecturer_additions (string med max 6 punktlistor där varje rad börjar med '- ')
- key_takeaways (array med exakt 3 strings)"""

KEY_ALIASES = {
    "summary": ("summary", "sammanfattning", "overview", "title"),
    "slide_content": (
        "slide_content",
        "slideContent",
        "slidecontent",
        "slide_text",
        "content",
        "slide_points",
        "what_slide_shows",
    ),
    "lecturer_additions": (
        "lecturer_additions",
        "lecturerAdditions",
        "lecturer_notes",
        "lecturerNotes",
        "speaker_notes",
        "speakerNotes",
        "additional_notes",
        "notes",
    ),
    "key_takeaways": (
        "key_takeaways",
        "keyTakeaways",
        "takeaways",
        "highlights",
        "important_points",
        "bullet_points",
    ),
}

BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)")


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


def resolve_enrichment_provider(provider: str | None = None) -> str:
    candidate = (provider or DEFAULT_ENRICH_PROVIDER).strip().lower()
    if candidate not in SUPPORTED_ENRICH_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_ENRICH_PROVIDERS))
        raise ValueError(f"Unsupported ENRICH_PROVIDER={candidate!r}. Supported: {supported}")
    return candidate


def default_enrichment_model(provider: str) -> str:
    if provider == "anthropic":
        return DEFAULT_ENRICH_MODEL_ANTHROPIC
    return DEFAULT_ENRICH_MODEL_GROQ


def create_enrichment_client(provider: str | None = None) -> Any:
    resolved = resolve_enrichment_provider(provider)
    if resolved == "anthropic":
        if anthropic is None:
            raise RuntimeError("anthropic package is required for ENRICH_PROVIDER=anthropic")
        return anthropic.Anthropic()

    if OpenAI is None:
        raise RuntimeError("openai package is required for ENRICH_PROVIDER=groq")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required for ENRICH_PROVIDER=groq")
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")


def truncate_transcript_for_prompt(transcript_text: str, max_words: int) -> str:
    words = transcript_text.split()
    if max_words <= 0:
        return ""
    if len(words) <= max_words:
        return _collapse_whitespace(transcript_text)

    head_words = max(1, int(max_words * 0.6))
    if head_words >= max_words:
        head_words = max_words - 1
    tail_words = max_words - head_words
    capped = words[:head_words] + words[-tail_words:]
    return " ".join(capped)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _usage_from_response(response: Any, provider: str) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    if provider == "anthropic":
        input_tokens = _safe_int(getattr(usage, "input_tokens", 0))
        output_tokens = _safe_int(getattr(usage, "output_tokens", 0))
    else:
        input_tokens = _safe_int(getattr(usage, "prompt_tokens", 0))
        output_tokens = _safe_int(getattr(usage, "completion_tokens", 0))

    total_tokens = _safe_int(getattr(usage, "total_tokens", input_tokens + output_tokens))
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _is_rate_limit_error(exc: Exception) -> bool:
    if anthropic is not None and isinstance(exc, anthropic.RateLimitError):
        return True
    return exc.__class__.__name__.lower() == "ratelimiterror"


def _is_connection_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    if "connection" in name or "timeout" in name:
        return True
    message = str(exc).lower()
    return "connection error" in message or "timeout" in message


def _add_usage(acc: dict[str, int], usage: dict[str, int]) -> None:
    acc["input_tokens"] += _safe_int(usage.get("input_tokens"))
    acc["output_tokens"] += _safe_int(usage.get("output_tokens"))
    acc["total_tokens"] += _safe_int(usage.get("total_tokens"))


def _response_text_from_groq_completion(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", "") if message is not None else ""
    if isinstance(content, list):
        # OpenAI-compatible SDKs may represent multimodal parts as a list.
        parts = []
        for part in content:
            text = part.get("text") if isinstance(part, dict) else None
            if text:
                parts.append(str(text))
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return str(content).strip()


def _call_enrichment_model(
    client: Any,
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> tuple[str, dict[str, int]]:
    if provider == "anthropic":
        response = client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        return raw, _usage_from_response(response, provider)

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=max_output_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    raw = _response_text_from_groq_completion(response)
    return raw, _usage_from_response(response, provider)


def build_user_prompt(slide: dict, transcript_text: str) -> str:
    return (
        f"BILD (Slide {slide['slide']}):\n{slide['text']}\n\n"
        f"TRANSKRIPTION AV FÖRELÄSARENS ORD:\n{transcript_text}"
    )


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        parts = [_string_value(v) for v in value]
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        parts = [_string_value(v) for v in value.values()]
        return "\n".join(p for p in parts if p)
    return str(value).strip()


def _normalize_takeaways(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = [_string_value(v) for v in value]
    elif isinstance(value, str):
        raw_items = re.split(r"(?:\r?\n|;|•|\*)", value)
    elif value is None:
        raw_items = []
    else:
        raw_items = [_string_value(value)]

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        normalized = item.strip(" \t\r\n-•")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _extract_prefixed_bullets(text: str) -> list[str]:
    lines = [
        line.strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    ]
    if not lines:
        return []

    items: list[str] = []
    for line in lines:
        match = BULLET_PREFIX_RE.match(line)
        if match:
            item = line[match.end():].strip()
            if item:
                items.append(item)
            continue
        if items:
            items[-1] = f"{items[-1]} {line}".strip()

    return items


def _split_text_to_bullets(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    prefixed_items = _extract_prefixed_bullets(normalized)
    if prefixed_items:
        return prefixed_items

    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if len(lines) > 1:
        return lines

    sentence_chunks = re.split(r"(?<=[.!?])\s+|;\s+", _collapse_whitespace(normalized))
    return [chunk.strip() for chunk in sentence_chunks if chunk.strip()]


def _format_lecturer_additions(value: Any) -> str:
    raw = _string_value(value)
    if not raw:
        return ""

    bullet_items = _split_text_to_bullets(raw)
    cleaned_items = [
        _collapse_whitespace(item.strip(" \t\r\n-•"))
        for item in bullet_items
        if item.strip(" \t\r\n-•")
    ]
    if not cleaned_items:
        fallback = _collapse_whitespace(raw)
        return f"- {fallback}" if fallback else ""

    return "\n".join(f"- {item}" for item in cleaned_items)


def _pick_first(payload: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        in_string = False
        escaped = False
        depth = 0
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:idx + 1]
        start = text.find("{", start + 1)
    return None


def _json_to_dict(candidate: str) -> dict | None:
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        return parsed[0]
    return None


def parse_enrichment_response(raw_text: str) -> dict | None:
    candidate = raw_text.strip()
    if not candidate:
        return None

    parsed = _json_to_dict(candidate)
    if parsed is not None:
        return parsed

    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        candidate,
        re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        parsed = _json_to_dict(fenced.group(1))
        if parsed is not None:
            return parsed

    extracted = _extract_first_json_object(candidate)
    if extracted:
        return _json_to_dict(extracted)
    return None


def normalize_enriched_payload(payload: dict) -> dict:
    summary = _string_value(_pick_first(payload, KEY_ALIASES["summary"]))
    slide_content = _string_value(_pick_first(payload, KEY_ALIASES["slide_content"]))
    lecturer_additions = _format_lecturer_additions(_pick_first(payload, KEY_ALIASES["lecturer_additions"]))
    key_takeaways = _normalize_takeaways(_pick_first(payload, KEY_ALIASES["key_takeaways"]))
    return {
        "summary": summary,
        "slide_content": slide_content,
        "lecturer_additions": lecturer_additions,
        "key_takeaways": key_takeaways,
    }


def is_enriched_payload_invalid(payload: dict | None) -> bool:
    if not payload:
        return True
    normalized = normalize_enriched_payload(payload)
    return (
        not normalized["summary"].strip()
        and not normalized["slide_content"].strip()
        and not normalized["lecturer_additions"].strip()
        and len(normalized["key_takeaways"]) == 0
    )


def _sentence_chunks(text: str, limit: int) -> list[str]:
    compact = _collapse_whitespace(text)
    if not compact:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", compact) if s.strip()]
    return sentences[:limit]


def build_fallback_enrichment(slide: dict, transcript_text: str) -> dict:
    slide_text = _collapse_whitespace(str(slide.get("text", "")))
    transcript_compact = _collapse_whitespace(transcript_text)
    slide_number = slide.get("slide", "?")

    summary_candidates = _sentence_chunks(transcript_compact, 1) or _sentence_chunks(slide_text, 1)
    summary = summary_candidates[0] if summary_candidates else f"Slide {slide_number} sammanfattar forelasningens innehall."

    slide_content = slide_text or "Slideinnehall kunde inte extraheras automatiskt."
    lecturer_additions = _format_lecturer_additions(
        transcript_compact or "Transkript saknas for denna slide."
    )

    takeaways = _sentence_chunks(transcript_compact, 3)
    if not takeaways:
        takeaways = [line.strip(" -•\t") for line in str(slide.get("text", "")).splitlines() if line.strip()][:3]
    if not takeaways:
        takeaways = [f"Se slide {slide_number} och transkriptet for fullstandig kontext."]

    return {
        "summary": summary,
        "slide_content": slide_content,
        "lecturer_additions": lecturer_additions,
        "key_takeaways": takeaways,
    }


def enrich_slide(
    client: Any,
    slide: dict,
    transcript_text: str,
    provider: str,
    model: str,
    max_output_tokens: int,
    system_prompt: str = SYSTEM_PROMPT,
) -> tuple[dict, dict[str, int]]:
    user_prompt = build_user_prompt(slide, transcript_text)
    raw, usage = _call_enrichment_model(
        client,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=max_output_tokens,
    )
    parsed = parse_enrichment_response(raw)
    if parsed is None:
        raise EnrichmentResponseError(
            f"No JSON object found in enrichment response: {raw[:240]}",
            usage=usage,
            reason="no_json",
        )

    normalized = normalize_enriched_payload(parsed)
    if is_enriched_payload_invalid(normalized):
        raise EnrichmentResponseError(
            "Enrichment response parsed but all canonical fields were empty",
            usage=usage,
            reason="empty_payload",
        )
    return normalized, usage


def enrich_slide_with_retry(
    client: Any,
    slide: dict,
    transcript_text: str,
    *,
    provider: str,
    model: str,
    max_output_tokens: int = DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
    max_transcript_words: int = DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
    max_attempts: int = DEFAULT_ENRICH_MAX_ATTEMPTS,
    log_usage: bool = DEFAULT_ENRICH_LOG_USAGE,
    log_callback: Callable[[str], None] | None = None,
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
        system_prompt = SYSTEM_PROMPT if attempt == 0 else STRICT_SYSTEM_PROMPT
        current_max_output_tokens = next_attempt_tokens or max_output_tokens
        next_attempt_tokens = None
        try:
            enriched, usage = enrich_slide(
                client,
                slide,
                prompt_transcript_text,
                provider=provider,
                model=model,
                max_output_tokens=current_max_output_tokens,
                system_prompt=system_prompt,
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
                    f"⚠️ Invalid enrichment payload on slide {slide_num} "
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
                wait = 60 * (attempt + 1)
                msg = f"⏳ Rate limited on slide {slide_num}, waiting {wait}s..."
                print(f"  {msg}", flush=True)
                if log_callback:
                    log_callback(msg)
                time.sleep(wait)
            else:
                if attempt < max_attempts - 1:
                    wait = min(8, attempt + 1)
                    msg = (
                        f"⚠️ Invalid enrichment payload on slide {slide_num} "
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


def enrich(
    slides_path: str,
    aligned_path: str,
    transcript_path: str,
    output_path: str,
    max_workers: int = DEFAULT_ENRICH_MAX_WORKERS,
    max_attempts: int = DEFAULT_ENRICH_MAX_ATTEMPTS,
    max_transcript_words: int = DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
    max_output_tokens: int = DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
    provider: str | None = None,
    model: str | None = None,
    log_usage: bool = DEFAULT_ENRICH_LOG_USAGE,
) -> None:
    with open(slides_path, encoding="utf-8") as f:
        slides = json.load(f)
    with open(aligned_path, encoding="utf-8") as f:
        aligned = json.load(f)
    with open(transcript_path, encoding="utf-8") as f:
        segments = json.load(f)

    slides_by_num = {s["slide"]: s for s in slides}

    # Load already-enriched slides from a previous run (resume support)
    try:
        with open(output_path, encoding="utf-8") as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = []

    already_done = {e["slide"] for e in existing}
    results = list(existing)
    results_lock = threading.Lock()

    pending = [a for a in aligned if a["slide"] not in already_done]
    total = len(aligned)

    if already_done:
        print(f"Resuming: {len(already_done)}/{total} slides already done, {len(pending)} remaining")

    resolved_provider = resolve_enrichment_provider(provider)
    resolved_model = (
        model.strip()
        if model and model.strip()
        else (DEFAULT_ENRICH_MODEL_OVERRIDE or default_enrichment_model(resolved_provider))
    )
    enrich_client = create_enrichment_client(resolved_provider)

    def process(a: dict) -> None:
        slide = slides_by_num[a["slide"]]
        transcript_segs = segments[a["start_segment"]: a["end_segment"] + 1]
        transcript_text = " ".join(s["text"].strip() for s in transcript_segs)

        enriched, _metrics = enrich_slide_with_retry(
            enrich_client,
            slide,
            transcript_text,
            provider=resolved_provider,
            model=resolved_model,
            max_output_tokens=max_output_tokens,
            max_transcript_words=max_transcript_words,
            max_attempts=max_attempts,
            log_usage=log_usage,
        )
        entry = {
            "slide": a["slide"],
            "original_text": slide["text"],
            "start_segment": a["start_segment"],
            "end_segment": a["end_segment"],
            **enriched,
        }

        with results_lock:
            results.append(entry)
            done_count = len(results)

        print(f"  Slide {a['slide']}/{total} done ({done_count}/{total} total)", flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(process, a) for a in pending]
        for future in as_completed(futures):
            future.result()  # re-raise any exceptions

    sorted_results = sorted(results, key=lambda x: x["slide"])
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sorted_results, f, ensure_ascii=False, indent=2)

    print(f"\nEnriched {len(results)} slides → {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich slides with lecturer transcript using AI")
    parser.add_argument("--slides", required=True)
    parser.add_argument("--aligned", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_ENRICH_MAX_WORKERS,
        help=f"Parallel API workers (default {DEFAULT_ENRICH_MAX_WORKERS})",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_ENRICH_MAX_ATTEMPTS,
        help=f"Retry attempts per slide (default {DEFAULT_ENRICH_MAX_ATTEMPTS})",
    )
    parser.add_argument(
        "--max-transcript-words",
        type=int,
        default=DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
        help=f"Max transcript words in enrichment prompt (default {DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS})",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
        help=f"Max completion tokens per enrichment call (default {DEFAULT_ENRICH_MAX_OUTPUT_TOKENS})",
    )
    parser.add_argument(
        "--provider",
        choices=sorted(SUPPORTED_ENRICH_PROVIDERS),
        default=DEFAULT_ENRICH_PROVIDER,
        help=f"LLM provider for enrichment (default {DEFAULT_ENRICH_PROVIDER})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_ENRICH_MODEL_OVERRIDE,
        help="Override model id for enrichment provider (default uses ENRICH_MODEL / ENRICH_MODEL_* env vars)",
    )
    parser.add_argument(
        "--log-usage",
        action="store_true",
        default=DEFAULT_ENRICH_LOG_USAGE,
        help="Log per-slide usage metrics (default follows ENRICH_LOG_USAGE)",
    )
    parser.add_argument(
        "--no-log-usage",
        action="store_false",
        dest="log_usage",
        help="Disable per-slide usage logging",
    )
    args = parser.parse_args()
    enrich(
        args.slides,
        args.aligned,
        args.transcript,
        args.output,
        max_workers=args.workers,
        max_attempts=args.max_attempts,
        max_transcript_words=args.max_transcript_words,
        max_output_tokens=args.max_output_tokens,
        provider=args.provider,
        model=args.model,
        log_usage=args.log_usage,
    )
