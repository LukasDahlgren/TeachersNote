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
DEFAULT_ENRICH_MAX_WORKERS = _env_int("ENRICH_MAX_WORKERS", 2, minimum=1)
DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS = _env_int("ENRICH_MAX_TRANSCRIPT_WORDS", 700, minimum=1)
DEFAULT_ENRICH_MAX_OUTPUT_TOKENS = _env_int("ENRICH_MAX_OUTPUT_TOKENS", 320, minimum=64)
DEFAULT_ENRICH_MAX_ATTEMPTS = _env_int("ENRICH_MAX_ATTEMPTS", 4, minimum=1)
DEFAULT_ENRICH_LOG_USAGE = _env_truthy("ENRICH_LOG_USAGE", True)

SUPPORTED_ENRICH_PROVIDERS = {"anthropic", "groq"}

SYSTEM_PROMPT = """Du är assistent som hjälper studenter att förstå föreläsningsinnehåll.
Du får en föreläsningsbild (slide) och en transkription av vad föreläsaren sade under den bilden.
Din uppgift är att skapa berikade anteckningar på svenska med strikt relevans till sliden:
1. Fokus ska vara det som visas eller direkt förklarar sliden.
2. Ignorera operativt prat och småprat (t.ex. kamera, mikrofon, ljud, pauser, adminpåminnelser).
3. I lecturer_additions får du ta med upp till 3 punkter som inte står på sliden, men bara om de är akademiskt kursrelevanta och hjälper studenten förstå ämnet djupare.
4. Ta aldrig med praktiska/logistiska detaljer som inte hjälper studenten förstå slideinnehållet.
5. Håll anteckningarna informativa, inte för korta: summary ska vara en fullständig informativ mening, slide_content ska ha 2-4 substantiella punkter, lecturer_additions ska ha 3-6 punkter när relevant material finns, och key_takeaways ska ha 2-4 konkreta punkter beroende på hur innehållsrikt sliden är.
6. Markera den viktigaste termen i varje punkt i slide_content, lecturer_additions och key_takeaways med markdown-formatet **viktig term** (helst en gång per punkt). Om föreläsaren definierade en term, skriv definitionen direkt efter termen i parentes: **term** (= definition).
7. Om föreläsaren gav ett konkret exempel eller analogi, inkludera det som en punkt i lecturer_additions med prefixet "Exempel: ...".
8. Om föreläsaren explicit markerade något som tentarelevant eller extra viktigt, lägg till prefixet "[Tentaviktigt]" på den punkten i lecturer_additions eller key_takeaways.

Svara ALLTID med ett JSON-objekt (inga kodblock, bara ren JSON) med dessa fält:
{
  "summary": "En komplett och informativ mening som sammanfattar slidens ämne och varför det är relevant i kursens sammanhang (om det framgår av transkriptionen)",
  "slide_content": "2-4 punktlistor där varje rad börjar med '- ' och är direkt slide-relevanta",
  "lecturer_additions": "3-6 punktlistor där varje rad börjar med '- '. Upp till 3 punkter får vara akademisk kontext utanför sliden.",
  "key_takeaways": ["2-4 takeaways beroende på slidens innehållsrikedom"]
}"""

STRICT_SYSTEM_PROMPT = """Du måste svara med ENDAST ett giltigt JSON-objekt.
Ingen inledande text, inga kodblock, inga extra nycklar.
Innehållet måste vara strikt slide-relevant.
Ignorera operativt prat/småprat (kamera, mikrofon, ljud, zoom, paus, admin).
I lecturer_additions får upp till 3 punkter vara akademisk kontext utanför sliden.
Undvik ultrakorta svar: summary ska vara informativ, slide_content ska normalt ha 2-4 punkter och key_takeaways ska ha 2-4 tydliga punkter beroende på slidens innehållsrikedom.
Markera viktigaste term i varje punkt i slide_content, lecturer_additions och key_takeaways med **...** (helst en gång per punkt). Om föreläsaren definierade en term, skriv definitionen direkt efter: **term** (= definition).
Om föreläsaren gav ett konkret exempel eller analogi, inkludera det i lecturer_additions med prefixet "Exempel: ...".
Om föreläsaren explicit markerade något som tentarelevant eller extra viktigt, lägg till prefixet "[Tentaviktigt]" på den punkten.
Använd exakt dessa nycklar:
- summary (string, en komplett informativ mening som förklarar ämnet och dess relevans om det framgår)
- slide_content (string med 2-4 punktlistor där varje rad börjar med '- ' och är slide-relevanta)
- lecturer_additions (string med 3-6 punktlistor där varje rad börjar med '- ', där upp till 3 punkter får vara icke-slide men akademiska)
- key_takeaways (array med 2-4 strings)"""

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
TOKEN_RE = re.compile(r"[a-zA-Z0-9åäöÅÄÖ]{3,}")

# Phrases/keywords that indicate operational chatter rather than content relevant to slide understanding.
OPERATIONAL_CHATTER_KEYWORDS = (
    "kamera",
    "camera",
    "mikrofon",
    "microphone",
    "mic",
    "ljud",
    "audio",
    "zoom",
    "teams",
    "meet",
    "inspeln",
    "recording",
    "stream",
    "paus",
    "rast",
    "break",
    "chatten",
    "chat",
    "admin",
    "närvaro",
    "attendance",
    "hdmi",
    "slido",
    "tekniskt strul",
    "tekniska problem",
)

# Keywords that can justify one "misc" point outside strict slide content.
ACADEMIC_MISC_KEYWORDS = (
    "tenta",
    "exam",
    "quiz",
    "uppgift",
    "inlämning",
    "deadline",
    "labb",
    "laboration",
    "project",
    "projekt",
    "kursbok",
    "litteratur",
    "referens",
    "metod",
    "modell",
    "algoritm",
    "teorem",
    "bevis",
    "definition",
    "begrepp",
)

RELEVANCE_STOPWORDS = {
    "och",
    "att",
    "det",
    "den",
    "som",
    "med",
    "for",
    "för",
    "på",
    "av",
    "till",
    "från",
    "this",
    "that",
    "with",
    "from",
    "into",
    "under",
    "over",
    "about",
    "som",
    "ska",
    "kan",
    "har",
    "var",
    "där",
    "here",
    "dessa",
    "olika",
    "samt",
    "också",
    "alltså",
    "eller",
}

MAX_MISC_ACADEMIC_BULLETS = 3
MAX_LECTURER_ADDITIONS_BULLETS = 6
MIN_LECTURER_ADDITIONS_BULLETS = 4
MIN_SLIDE_CONTENT_BULLETS = 2
MAX_SLIDE_CONTENT_BULLETS = 4
MIN_KEY_TAKEAWAYS = 2
MAX_KEY_TAKEAWAYS = 4
TARGET_MIN_DEPTH_RATIO = 1.0
MIN_NOTE_WORD_FLOOR = 60
MAX_NOTE_WORD_FLOOR = 280
SUMMARY_MIN_WORDS = 12


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
    if anthropic is not None:
        _overloaded = getattr(anthropic, 'OverloadedError', None)
        _types = (anthropic.RateLimitError,) + ((_overloaded,) if _overloaded else ())
        if isinstance(exc, _types):
            return True
    name = exc.__class__.__name__.lower()
    return name in ("ratelimiterror", "overloadederror")


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
        extra_body={"thinking": {"type": "disabled"}},
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


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _tokenize_for_relevance(text: str) -> set[str]:
    if not text:
        return set()
    tokens = {match.group(0).lower() for match in TOKEN_RE.finditer(text)}
    return {t for t in tokens if t not in RELEVANCE_STOPWORDS}


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _is_operational_chatter(text: str) -> bool:
    return _contains_keyword(text, OPERATIONAL_CHATTER_KEYWORDS)


def _is_academic_misc_context(text: str) -> bool:
    return _contains_keyword(text, ACADEMIC_MISC_KEYWORDS)


def _word_count(text: str) -> int:
    return len(_collapse_whitespace(text).split())


def _slide_text_fragments(slide_text: str) -> list[str]:
    fragments = _clean_lines_for_relevance(slide_text)
    if not fragments:
        return []
    expanded: list[str] = []
    for fragment in fragments:
        chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+|;\s+", fragment) if c.strip()]
        if len(chunks) > 1:
            expanded.extend(chunks)
        else:
            expanded.append(fragment)
    return _dedupe_keep_order([f for f in expanded if f])


def _to_summary_sentence(text: str) -> str:
    value = _collapse_whitespace(text.strip(" \t\r\n-•"))
    if not value:
        return ""
    if value[-1] in ".!?":
        return value
    return f"{value}."


def _candidate_source_priority(source: str) -> int:
    order = {
        "lecturer_additions": 0,
        "key_takeaways": 1,
        "slide_content": 2,
        "slide_text": 3,
        "summary": 4,
    }
    return order.get(source, 99)


def _classify_relevance_tier(text: str, slide_terms: set[str]) -> tuple[str, int]:
    cleaned = _collapse_whitespace(text)
    if not cleaned or _is_operational_chatter(cleaned):
        return "weak", 0

    text_terms = _tokenize_for_relevance(cleaned)
    overlap = len(text_terms & slide_terms) if slide_terms else 0

    if not slide_terms:
        # Avoid over-pruning when OCR text is weak/missing.
        if _is_academic_misc_context(cleaned):
            return "strong", overlap
        return "moderate", overlap

    if overlap >= 2:
        return "strong", overlap
    if overlap == 1 and len(text_terms) <= 8:
        return "strong", overlap
    if overlap == 1:
        return "moderate", overlap
    if _is_academic_misc_context(cleaned):
        return "moderate", overlap
    return "weak", overlap


def _make_candidate(
    text: str,
    *,
    source: str,
    slide_terms: set[str],
    order: int,
) -> dict[str, Any]:
    cleaned = _collapse_whitespace(text.strip(" \t\r\n-•"))
    tier, overlap = _classify_relevance_tier(cleaned, slide_terms)
    return {
        "text": cleaned,
        "source": source,
        "tier": tier,
        "overlap": overlap,
        "academic_misc": _is_academic_misc_context(cleaned),
        "slide_related": overlap > 0 or not slide_terms,
        "word_count": _word_count(cleaned),
        "order": order,
    }


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        -int(candidate["overlap"]),
        -int(candidate["word_count"]),
        _candidate_source_priority(str(candidate["source"])),
        int(candidate["order"]),
    )


def _candidate_words(candidates: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    total = 0
    for candidate in candidates:
        text = str(candidate["text"])
        if text in seen:
            continue
        seen.add(text)
        total += _word_count(text)
    return total


def _depth_word_count(summary: str, lecturer_items: list[str], takeaways: list[str]) -> int:
    parts = [summary] + lecturer_items + takeaways
    return _word_count(" ".join(parts))


def _clean_lines_for_relevance(value: str) -> list[str]:
    items = _split_text_to_bullets(value)
    cleaned = [
        _collapse_whitespace(item.strip(" \t\r\n-•"))
        for item in items
        if item.strip(" \t\r\n-•")
    ]
    if cleaned:
        return cleaned
    fallback = _collapse_whitespace(value.strip(" \t\r\n-•"))
    return [fallback] if fallback else []


def _format_bullets(items: list[str]) -> str:
    deduped = _dedupe_keep_order(items)
    return "\n".join(f"- {item}" for item in deduped if item)


def enforce_relevance_policy(payload: dict, slide_text: str) -> dict:
    normalized = normalize_enriched_payload(payload)
    slide_terms = _tokenize_for_relevance(slide_text)
    summary_raw = _collapse_whitespace(normalized["summary"])
    slide_content_raw = _clean_lines_for_relevance(normalized["slide_content"])
    lecturer_raw = _clean_lines_for_relevance(normalized["lecturer_additions"])
    takeaways_raw = [
        _collapse_whitespace(str(item).strip(" \t\r\n-•"))
        for item in normalized["key_takeaways"]
        if _collapse_whitespace(str(item).strip(" \t\r\n-•"))
    ]
    slide_fragments = _slide_text_fragments(slide_text)

    order_counter = 0
    summary_candidates: list[dict[str, Any]] = []
    if summary_raw:
        summary_candidates.append(_make_candidate(summary_raw, source="summary", slide_terms=slide_terms, order=order_counter))
        order_counter += 1

    slide_candidates: list[dict[str, Any]] = []
    for item in slide_content_raw:
        slide_candidates.append(_make_candidate(item, source="slide_content", slide_terms=slide_terms, order=order_counter))
        order_counter += 1

    lecturer_candidates: list[dict[str, Any]] = []
    for item in lecturer_raw:
        lecturer_candidates.append(
            _make_candidate(item, source="lecturer_additions", slide_terms=slide_terms, order=order_counter)
        )
        order_counter += 1

    takeaway_candidates: list[dict[str, Any]] = []
    for item in takeaways_raw:
        takeaway_candidates.append(_make_candidate(item, source="key_takeaways", slide_terms=slide_terms, order=order_counter))
        order_counter += 1

    slide_fragment_candidates: list[dict[str, Any]] = []
    for item in slide_fragments:
        slide_fragment_candidates.append(_make_candidate(item, source="slide_text", slide_terms=slide_terms, order=order_counter))
        order_counter += 1

    all_candidates = summary_candidates + slide_candidates + lecturer_candidates + takeaway_candidates + slide_fragment_candidates
    strong_candidates = [c for c in all_candidates if c["tier"] == "strong"]
    moderate_candidates = [c for c in all_candidates if c["tier"] == "moderate"]

    summary = ""
    for pool in (
        [c for c in summary_candidates if c["tier"] == "strong"],
        [c for c in summary_candidates if c["tier"] == "moderate"],
        [c for c in strong_candidates if c["source"] != "summary"],
        [c for c in moderate_candidates if c["source"] != "summary"],
    ):
        if pool:
            summary = _to_summary_sentence(str(pool[0]["text"]))
            break
    if not summary and slide_fragments:
        summary = _to_summary_sentence(slide_fragments[0])
    if _word_count(summary) < SUMMARY_MIN_WORDS:
        summary_boosters = sorted(
            [c for c in strong_candidates + moderate_candidates if c["source"] != "summary"],
            key=_candidate_sort_key,
        )
        for candidate in summary_boosters:
            candidate_sentence = _to_summary_sentence(str(candidate["text"]))
            if _word_count(candidate_sentence) > _word_count(summary):
                summary = candidate_sentence
            if _word_count(summary) >= SUMMARY_MIN_WORDS:
                break

    slide_content_items: list[str] = []
    slide_seen: set[str] = set()

    def _append_slide_candidate(candidate: dict[str, Any], *, require_slide_related: bool = True) -> None:
        if len(slide_content_items) >= MAX_SLIDE_CONTENT_BULLETS:
            return
        text = str(candidate["text"])
        if not text or text in slide_seen:
            return
        if candidate["tier"] == "weak":
            return
        if require_slide_related and not bool(candidate["slide_related"]):
            return
        slide_seen.add(text)
        slide_content_items.append(text)

    for candidate in slide_candidates:
        if candidate["tier"] == "strong":
            _append_slide_candidate(candidate)
    for candidate in slide_candidates:
        if candidate["tier"] == "moderate":
            _append_slide_candidate(candidate)
    for candidate in lecturer_candidates + takeaway_candidates + slide_fragment_candidates:
        if len(slide_content_items) >= MIN_SLIDE_CONTENT_BULLETS:
            break
        if candidate["tier"] == "strong":
            _append_slide_candidate(candidate)
    for candidate in lecturer_candidates + takeaway_candidates + slide_fragment_candidates:
        if len(slide_content_items) >= MIN_SLIDE_CONTENT_BULLETS:
            break
        if candidate["tier"] == "moderate":
            _append_slide_candidate(candidate)
    for fragment in slide_fragments:
        if len(slide_content_items) >= MIN_SLIDE_CONTENT_BULLETS:
            break
        cleaned = _collapse_whitespace(fragment.strip(" \t\r\n-•"))
        if cleaned and cleaned not in slide_seen and not _is_operational_chatter(cleaned):
            slide_seen.add(cleaned)
            slide_content_items.append(cleaned)
    slide_content_items = _dedupe_keep_order(slide_content_items)[:MAX_SLIDE_CONTENT_BULLETS]

    lecturer_items_out: list[str] = []
    lecturer_seen: set[str] = set()
    misc_count = 0

    def _append_lecturer_candidate(candidate: dict[str, Any], *, allow_misc: bool) -> None:
        nonlocal misc_count
        if len(lecturer_items_out) >= MAX_LECTURER_ADDITIONS_BULLETS:
            return
        text = str(candidate["text"])
        if not text or text in lecturer_seen:
            return
        if candidate["tier"] == "weak":
            return
        if candidate["slide_related"]:
            lecturer_seen.add(text)
            lecturer_items_out.append(text)
            return
        if allow_misc and candidate["academic_misc"] and misc_count < MAX_MISC_ACADEMIC_BULLETS:
            misc_count += 1
            lecturer_seen.add(text)
            lecturer_items_out.append(text)

    for candidate in lecturer_candidates:
        if candidate["tier"] == "strong":
            _append_lecturer_candidate(candidate, allow_misc=True)
    for candidate in lecturer_candidates:
        if candidate["tier"] == "moderate":
            _append_lecturer_candidate(candidate, allow_misc=True)

    for candidate in slide_candidates + takeaway_candidates + slide_fragment_candidates:
        if len(lecturer_items_out) >= MIN_LECTURER_ADDITIONS_BULLETS:
            break
        if candidate["tier"] in {"strong", "moderate"} and candidate["slide_related"]:
            _append_lecturer_candidate(candidate, allow_misc=False)
    lecturer_items_out = _dedupe_keep_order(lecturer_items_out)[:MAX_LECTURER_ADDITIONS_BULLETS]

    takeaways: list[str] = []
    takeaway_seen: set[str] = set()

    def _append_takeaway_candidate(candidate: dict[str, Any], *, require_slide_related: bool = True) -> None:
        if len(takeaways) >= MAX_KEY_TAKEAWAYS:
            return
        text = str(candidate["text"])
        if not text or text in takeaway_seen:
            return
        if candidate["tier"] == "weak":
            return
        if require_slide_related and not bool(candidate["slide_related"]):
            return
        takeaway_seen.add(text)
        takeaways.append(text)

    for candidate in takeaway_candidates:
        if candidate["tier"] == "strong":
            _append_takeaway_candidate(candidate)
    for candidate in takeaway_candidates:
        if candidate["tier"] == "moderate":
            _append_takeaway_candidate(candidate)
    for candidate in slide_candidates + lecturer_candidates:
        if len(takeaways) >= MIN_KEY_TAKEAWAYS:
            break
        if candidate["tier"] == "strong":
            _append_takeaway_candidate(candidate)
    for candidate in slide_candidates + lecturer_candidates + slide_fragment_candidates:
        if len(takeaways) >= MIN_KEY_TAKEAWAYS:
            break
        if candidate["tier"] == "moderate":
            _append_takeaway_candidate(candidate)
    for fragment in slide_fragments:
        if len(takeaways) >= MIN_KEY_TAKEAWAYS:
            break
        cleaned = _collapse_whitespace(fragment.strip(" \t\r\n-•"))
        if cleaned and cleaned not in takeaway_seen and not _is_operational_chatter(cleaned):
            takeaway_seen.add(cleaned)
            takeaways.append(cleaned)
    takeaways = _dedupe_keep_order(takeaways)[:MAX_KEY_TAKEAWAYS]

    depth_source_candidates = [c for c in all_candidates if c["tier"] in {"strong", "moderate"}]
    source_words = _candidate_words(depth_source_candidates)
    if source_words <= 0:
        source_words = _candidate_words([c for c in slide_candidates + slide_fragment_candidates if c["tier"] != "weak"])
    target_word_floor = max(MIN_NOTE_WORD_FLOOR, int(source_words * TARGET_MIN_DEPTH_RATIO))
    target_word_floor = min(target_word_floor, MAX_NOTE_WORD_FLOOR)

    current_depth_words = _depth_word_count(summary, lecturer_items_out, takeaways)
    if current_depth_words < target_word_floor:
        recovery_candidates = sorted(
            [
                c
                for c in all_candidates
                if c["tier"] in {"strong", "moderate"}
                and c["source"] in {"lecturer_additions", "key_takeaways", "slide_content", "slide_text"}
            ],
            key=_candidate_sort_key,
        )
        for candidate in recovery_candidates:
            if current_depth_words >= target_word_floor:
                break
            text = str(candidate["text"])
            if text in lecturer_seen or text in takeaway_seen:
                continue
            if len(lecturer_items_out) < MAX_LECTURER_ADDITIONS_BULLETS:
                pre_count = len(lecturer_items_out)
                _append_lecturer_candidate(candidate, allow_misc=True)
                if len(lecturer_items_out) > pre_count:
                    current_depth_words = _depth_word_count(summary, lecturer_items_out, takeaways)
                    continue
            if len(takeaways) < MAX_KEY_TAKEAWAYS and candidate["slide_related"]:
                _append_takeaway_candidate(candidate, require_slide_related=True)
                current_depth_words = _depth_word_count(summary, lecturer_items_out, takeaways)

    if not summary:
        if slide_content_items:
            summary = _to_summary_sentence(slide_content_items[0])
        elif takeaways:
            summary = _to_summary_sentence(takeaways[0])
        elif lecturer_items_out:
            summary = _to_summary_sentence(lecturer_items_out[0])
        elif slide_fragments:
            summary = _to_summary_sentence(slide_fragments[0])

    while len(slide_content_items) < MIN_SLIDE_CONTENT_BULLETS and len(slide_content_items) < MAX_SLIDE_CONTENT_BULLETS:
        candidate = next((t for t in lecturer_items_out + takeaways + slide_fragments if t not in slide_seen), "")
        if not candidate:
            break
        slide_seen.add(candidate)
        slide_content_items.append(candidate)

    while len(takeaways) < MIN_KEY_TAKEAWAYS and len(takeaways) < MAX_KEY_TAKEAWAYS:
        candidate = next((t for t in slide_content_items + lecturer_items_out + slide_fragments if t not in takeaway_seen), "")
        if not candidate:
            break
        takeaway_seen.add(candidate)
        takeaways.append(candidate)

    slide_content = _format_bullets(slide_content_items[:MAX_SLIDE_CONTENT_BULLETS])
    lecturer_additions = _format_bullets(lecturer_items_out[:MAX_LECTURER_ADDITIONS_BULLETS])
    takeaways = _dedupe_keep_order([_collapse_whitespace(t) for t in takeaways if t])[:MAX_KEY_TAKEAWAYS]

    return {
        "summary": _collapse_whitespace(summary),
        "slide_content": slide_content,
        "lecturer_additions": lecturer_additions,
        "key_takeaways": takeaways,
    }


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

    # Strip <think>...</think> reasoning blocks (e.g. Qwen3 thinking mode)
    candidate = re.sub(r"<think>.*?</think>", "", candidate, flags=re.DOTALL).strip()
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
    filtered = enforce_relevance_policy(normalized, str(slide.get("text", "")))
    if is_enriched_payload_invalid(filtered):
        raise EnrichmentResponseError(
            "Enrichment response parsed but all canonical fields were empty",
            usage=usage,
            reason="empty_payload",
        )
    return filtered, usage


_HEARTBEAT_INTERVAL = 10  # seconds between progress pings during a long sleep


def _sleep_with_heartbeat(
    total_seconds: int,
    *,
    slide_num: Any,
    log_callback: Callable[[str], None] | None,
) -> None:
    """Sleep for total_seconds, emitting a countdown log every _HEARTBEAT_INTERVAL seconds."""
    remaining = total_seconds
    while remaining > 0:
        chunk = min(_HEARTBEAT_INTERVAL, remaining)
        time.sleep(chunk)
        remaining -= chunk
        if remaining > 0 and log_callback:
            log_callback(f"⏳ Slide {slide_num}: rate-limited, ~{remaining}s remaining...")


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
        system_prompt = STRICT_SYSTEM_PROMPT
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
