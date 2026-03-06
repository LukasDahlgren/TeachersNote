import re
from typing import Any

try:
    from .enrich_parsing import (
        BULLET_PREFIX_RE,
        MARKDOWN_BOLD_RE,
        _collapse_whitespace,
        _normalize_slide_text,
        _split_text_to_bullets,
        normalize_enriched_payload,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from enrich_parsing import (
        BULLET_PREFIX_RE,
        MARKDOWN_BOLD_RE,
        _collapse_whitespace,
        _normalize_slide_text,
        _split_text_to_bullets,
        normalize_enriched_payload,
    )


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
MAX_LECTURER_ADDITIONS_BULLETS = 4
MIN_SLIDE_CONTENT_BULLETS = 2
MAX_SLIDE_CONTENT_BULLETS = 4
MIN_KEY_TAKEAWAYS = 2
MAX_KEY_TAKEAWAYS = 4
MIN_BULLET_WORDS = 4
TARGET_MIN_DEPTH_RATIO = 1.0
MIN_NOTE_WORD_FLOOR = 60
MAX_NOTE_WORD_FLOOR = 280
SUMMARY_MIN_WORDS = 12


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


def _normalize_for_duplicate_check(text: str) -> str:
    without_bold = MARKDOWN_BOLD_RE.sub(r"\1", text or "")
    without_bullets = BULLET_PREFIX_RE.sub("", without_bold, count=1)
    return _collapse_whitespace(without_bullets.strip(" \t\r\n-•")).lower()


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


def _format_bullets(items: list[str]) -> str:
    deduped = _dedupe_keep_order(items)
    return "\n".join(f"- {item}" for item in deduped if item)


def enforce_relevance_policy(payload: dict, slide_text: str) -> dict:
    normalized = normalize_enriched_payload(payload)
    normalized_slide_text = _normalize_slide_text(slide_text)
    slide_terms = _tokenize_for_relevance(normalized_slide_text)
    summary_raw = _collapse_whitespace(normalized["summary"])
    slide_content_raw = _clean_lines_for_relevance(normalized["slide_content"])
    lecturer_raw = _clean_lines_for_relevance(normalized["lecturer_additions"])
    takeaways_raw = [
        _collapse_whitespace(str(item).strip(" \t\r\n-•"))
        for item in normalized["key_takeaways"]
        if _collapse_whitespace(str(item).strip(" \t\r\n-•"))
    ]
    slide_fragments = _slide_text_fragments(normalized_slide_text)
    slide_duplicate_keys = {
        key
        for key in {
            _normalize_for_duplicate_check(normalized_slide_text),
            *(_normalize_for_duplicate_check(fragment) for fragment in slide_fragments),
        }
        if key
    }

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
        if _word_count(text) < MIN_BULLET_WORDS:
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
        if cleaned and cleaned not in slide_seen and not _is_operational_chatter(cleaned) and _word_count(cleaned) >= MIN_BULLET_WORDS:
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
        if _word_count(text) < MIN_BULLET_WORDS:
            return
        if candidate["tier"] == "weak":
            return
        if _normalize_for_duplicate_check(text) in slide_duplicate_keys:
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
    lecturer_items_out = _dedupe_keep_order(lecturer_items_out)[:MAX_LECTURER_ADDITIONS_BULLETS]

    takeaways: list[str] = []
    takeaway_seen: set[str] = set()

    def _append_takeaway_candidate(candidate: dict[str, Any], *, require_slide_related: bool = True) -> None:
        if len(takeaways) >= MAX_KEY_TAKEAWAYS:
            return
        text = str(candidate["text"])
        if not text or text in takeaway_seen:
            return
        if _word_count(text) < MIN_BULLET_WORDS:
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
        if cleaned and cleaned not in takeaway_seen and not _is_operational_chatter(cleaned) and _word_count(cleaned) >= MIN_BULLET_WORDS:
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
            if len(lecturer_items_out) < MAX_LECTURER_ADDITIONS_BULLETS and candidate["source"] == "lecturer_additions":
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
        candidate = next((t for t in lecturer_items_out + takeaways + slide_fragments if t not in slide_seen and _word_count(t) >= MIN_BULLET_WORDS), "")
        if not candidate:
            break
        slide_seen.add(candidate)
        slide_content_items.append(candidate)

    while len(takeaways) < MIN_KEY_TAKEAWAYS and len(takeaways) < MAX_KEY_TAKEAWAYS:
        candidate = next((t for t in slide_content_items + lecturer_items_out + slide_fragments if t not in takeaway_seen and _word_count(t) >= MIN_BULLET_WORDS), "")
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
