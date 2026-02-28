import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import anthropic

client = anthropic.Anthropic()

SYSTEM_PROMPT = """Du är assistent som hjälper studenter att förstå föreläsningsinnehåll.
Du får en föreläsningsbild (slide) och en transkription av vad föreläsaren sade under den bilden.
Din uppgift är att skapa berikade anteckningar på svenska som fångar:
1. Vad bilden visar (sammanfattning av slidens text)
2. Viktiga saker föreläsaren nämnde som INTE framgår av bilden
3. Exempel, förklaringar och anekdoter som föreläsaren gav
4. Praktiska råd eller varningar föreläsaren lyfte fram

Svara ALLTID med ett JSON-objekt (inga kodblock, bara ren JSON) med dessa fält:
{
  "summary": "En mening som sammanfattar slidens ämne",
  "slide_content": "Vad bilden visar (punktlista)",
  "lecturer_additions": "Punktlista med en punkt per rad där varje rad börjar med '- ' och innehåller allt relevant från föreläsaren utöver bilden",
  "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"]
}"""

STRICT_SYSTEM_PROMPT = """Du måste svara med ENDAST ett giltigt JSON-objekt.
Ingen inledande text, inga kodblock, inga extra nycklar.
Använd exakt dessa nycklar:
- summary (string)
- slide_content (string)
- lecturer_additions (string där varje rad börjar med '- ')
- key_takeaways (array av strings)"""

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
    client: anthropic.Anthropic,
    slide: dict,
    transcript_text: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict:
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": build_user_prompt(slide, transcript_text)}],
    )
    raw = response.content[0].text.strip()
    parsed = parse_enrichment_response(raw)
    if parsed is None:
        raise ValueError(f"No JSON object found in enrichment response: {raw[:240]}")

    normalized = normalize_enriched_payload(parsed)
    if is_enriched_payload_invalid(normalized):
        raise ValueError("Enrichment response parsed but all canonical fields were empty")
    return normalized


def enrich_slide_with_retry(
    client: anthropic.Anthropic,
    slide: dict,
    transcript_text: str,
    max_attempts: int = 5,
) -> dict:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        system_prompt = SYSTEM_PROMPT if attempt == 0 else STRICT_SYSTEM_PROMPT
        try:
            return enrich_slide(client, slide, transcript_text, system_prompt=system_prompt)
        except anthropic.RateLimitError as exc:
            last_error = exc
            wait = 60 * (attempt + 1)
            print(f"  ⏳ Rate limited on slide {slide.get('slide', '?')}, waiting {wait}s...", flush=True)
            time.sleep(wait)
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                wait = min(8, attempt + 1)
                print(
                    f"  ⚠️  Invalid enrichment payload on slide {slide.get('slide', '?')} (attempt {attempt + 1}/{max_attempts}), retrying in {wait}s...",
                    flush=True,
                )
                time.sleep(wait)
            else:
                break

    print(
        f"  ⚠️  Falling back to deterministic notes for slide {slide.get('slide', '?')} after repeated errors: {last_error}",
        flush=True,
    )
    return build_fallback_enrichment(slide, transcript_text)


def enrich(slides_path: str, aligned_path: str, transcript_path: str, output_path: str, max_workers: int = 8) -> None:
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

    def process(a: dict) -> None:
        slide = slides_by_num[a["slide"]]
        transcript_segs = segments[a["start_segment"]: a["end_segment"] + 1]
        transcript_text = " ".join(s["text"].strip() for s in transcript_segs)

        enriched = enrich_slide_with_retry(client, slide, transcript_text)
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
    parser = argparse.ArgumentParser(description="Enrich slides with lecturer transcript using Claude")
    parser.add_argument("--slides", required=True)
    parser.add_argument("--aligned", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=8, help="Parallel API workers (default 8)")
    args = parser.parse_args()
    enrich(args.slides, args.aligned, args.transcript, args.output, max_workers=args.workers)
