import json
import re
from typing import Any


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
MARKDOWN_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")


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


def _should_merge_wrapped_line(previous: str, current: str) -> bool:
    previous_clean = BULLET_PREFIX_RE.sub("", previous, count=1).rstrip()
    current_clean = current.strip()
    if not previous_clean or not current_clean:
        return False

    first = current_clean[0]
    if first.islower():
        return True
    if first in ",.;:!?)]}%":
        return True
    return previous_clean.endswith((",", ";", ":", "-", "–", "—", "/", "("))


def _merge_wrapped_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if (
            merged
            and not BULLET_PREFIX_RE.match(line)
            and not BULLET_PREFIX_RE.match(merged[-1])
            and _should_merge_wrapped_line(merged[-1], line)
        ):
            merged[-1] = f"{merged[-1]} {line}".strip()
            continue
        merged.append(line)
    return merged


def _normalize_slide_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    blocks: list[str] = []
    paragraph_lines: list[str] = []
    active_bullet: str | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            blocks.extend(_merge_wrapped_lines(paragraph_lines))
            paragraph_lines = []

    def flush_bullet() -> None:
        nonlocal active_bullet
        if active_bullet:
            blocks.append(active_bullet)
            active_bullet = None

    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_bullet()
            flush_paragraph()
            continue

        match = BULLET_PREFIX_RE.match(line)
        if match:
            flush_bullet()
            flush_paragraph()
            item = line[match.end():].strip()
            if item:
                active_bullet = f"- {item}"
            continue

        if active_bullet is not None:
            if _should_merge_wrapped_line(active_bullet, line):
                active_bullet = f"{active_bullet} {line}".strip()
            else:
                flush_bullet()
                paragraph_lines.append(line)
            continue

        paragraph_lines.append(line)

    flush_bullet()
    flush_paragraph()
    return "\n".join(block for block in blocks if block)


def _split_text_to_bullets(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    prefixed_items = _extract_prefixed_bullets(normalized)
    if prefixed_items:
        return prefixed_items

    lines = _merge_wrapped_lines([line.strip() for line in normalized.split("\n") if line.strip()])
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


def _extract_first_json_block(text: str, opener: str, closer: str) -> str | None:
    start = text.find(opener)
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

            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return text[start:idx + 1]
        start = text.find(opener, start + 1)
    return None


def _extract_first_json_object(text: str) -> str | None:
    return _extract_first_json_block(text, "{", "}")


def _extract_first_json_array(text: str) -> str | None:
    return _extract_first_json_block(text, "[", "]")


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


def _json_to_list_of_dicts(candidate: str) -> list[dict] | None:
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        return parsed
    if isinstance(parsed, dict):
        for key in ("slides", "results", "items", "enriched_slides"):
            value = parsed.get(key)
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value
        return [parsed]
    return None


def _strip_reasoning_blocks(raw_text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()


def _iter_fenced_json_candidates(candidate: str) -> list[str]:
    return re.findall(
        r"```(?:json)?\s*(.*?)\s*```",
        candidate,
        re.DOTALL | re.IGNORECASE,
    )


def parse_enrichment_response(raw_text: str) -> dict | None:
    candidate = raw_text.strip()
    if not candidate:
        return None

    candidate = _strip_reasoning_blocks(candidate)
    if not candidate:
        return None

    parsed = _json_to_dict(candidate)
    if parsed is not None:
        return parsed

    for fenced in _iter_fenced_json_candidates(candidate):
        parsed = _json_to_dict(fenced)
        if parsed is not None:
            return parsed

    extracted = _extract_first_json_object(candidate)
    if extracted:
        return _json_to_dict(extracted)
    return None


def parse_enrichment_batch_response(raw_text: str) -> list[dict] | None:
    candidate = raw_text.strip()
    if not candidate:
        return None

    candidate = _strip_reasoning_blocks(candidate)
    if not candidate:
        return None

    parsed = _json_to_list_of_dicts(candidate)
    if parsed is not None:
        return parsed

    for fenced in _iter_fenced_json_candidates(candidate):
        parsed = _json_to_list_of_dicts(fenced)
        if parsed is not None:
            return parsed

    extracted_array = _extract_first_json_array(candidate)
    if extracted_array:
        parsed = _json_to_list_of_dicts(extracted_array)
        if parsed is not None:
            return parsed

    extracted_object = _extract_first_json_object(candidate)
    if extracted_object:
        return _json_to_list_of_dicts(extracted_object)
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
