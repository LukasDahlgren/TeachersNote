import argparse
import json
import re
import anthropic

client = anthropic.Anthropic()


def _collapse_whitespace(text: str) -> str:
    return " ".join(str(text).split())


def _truncate_text(text: str, *, max_chars: int) -> str:
    compact = _collapse_whitespace(text)
    if max_chars <= 0 or len(compact) <= max_chars:
        return compact
    if max_chars <= 3:
        return compact[:max_chars]
    return f"{compact[: max_chars - 3].rstrip()}..."


def _sample_segment_indexes(total_segments: int, max_segments: int) -> list[int]:
    if max_segments <= 0 or total_segments <= max_segments:
        return list(range(total_segments))
    if max_segments == 1:
        return [0]

    indexes = {0, total_segments - 1}
    step = (total_segments - 1) / (max_segments - 1)
    for i in range(1, max_segments - 1):
        indexes.add(int(round(i * step)))
    return sorted(indexes)


def _prepare_segments_for_prompt(
    segments: list[dict],
    *,
    max_segments: int | None,
    max_segment_chars: int,
) -> tuple[list[dict], bool]:
    if not segments:
        return [], False

    indexes = (
        _sample_segment_indexes(len(segments), max_segments)
        if max_segments is not None
        else list(range(len(segments)))
    )
    sampled = len(indexes) < len(segments)
    prepared: list[dict] = []
    for idx in indexes:
        seg = segments[idx]
        prepared.append({
            "segment_index": idx,
            "start": float(seg.get("start", 0.0)),
            "text": _truncate_text(str(seg.get("text", "")), max_chars=max_segment_chars),
        })
    return prepared, sampled


def build_prompt(
    slides: list[dict],
    segments: list[dict],
    *,
    max_segments: int | None = None,
    max_segment_chars: int = 180,
    max_slide_chars: int = 1200,
) -> str:
    lines = ["SLIDES (presented in order during the lecture):"]
    for slide in slides:
        text = _truncate_text(str(slide.get("text", "")), max_chars=max_slide_chars)
        lines.append(f"\nSlide {slide['slide']}:\n{text}")

    prompt_segments, sampled = _prepare_segments_for_prompt(
        segments,
        max_segments=max_segments,
        max_segment_chars=max_segment_chars,
    )

    lines.append("\n\nTRANSCRIPT (numbered segments with timestamps):")
    for seg in prompt_segments:
        lines.append(f"[{seg['segment_index']}] {seg['start']:.1f}s: {seg['text']}")

    n = len(slides)
    lines.append(
        f"\n\nThe lecturer presents these {n} slides in order during this lecture."
        "\nIdentify which transcript segment starts the discussion of each slide."
        "\nReturn ONLY a JSON array like:"
        '\n[{"slide": 1, "start_segment": 0}, {"slide": 2, "start_segment": 46}, ...]'
        "\nRules:"
        "\n- slide 1 always starts at segment 0"
        "\n- start_segment values must be strictly increasing"
        "\n- every segment must belong to exactly one slide"
        f"\n- return all {n} slides"
    )
    if sampled:
        lines.append(
            "\n- the transcript list is sampled for length; "
            "start_segment values MUST use one of the listed segment indices"
        )
    return "\n".join(lines)


def parse_response(response_text: str) -> list[dict]:
    # Extract JSON array from response (in case Claude adds surrounding text)
    match = re.search(r"\[.*?\]", response_text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array found in response:\n{response_text[:500]}")
    return json.loads(match.group())


def align(slides_path: str, transcript_path: str, output_path: str) -> None:
    with open(slides_path, encoding="utf-8") as f:
        slides = json.load(f)
    with open(transcript_path, encoding="utf-8") as f:
        segments = json.load(f)

    print(f"Loaded {len(slides)} slides and {len(segments)} transcript segments")
    print("Calling Claude API for alignment...")

    prompt = build_prompt(slides, segments)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text
    boundaries = parse_response(response_text)
    boundaries.sort(key=lambda x: x["slide"])

    # Derive end_segment from the next slide's start_segment
    result = []
    for i, b in enumerate(boundaries):
        start = b["start_segment"]
        end = boundaries[i + 1]["start_segment"] - 1 if i + 1 < len(boundaries) else len(segments) - 1
        result.append({"slide": b["slide"], "start_segment": start, "end_segment": end})

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Aligned {len(result)} slides → {output_path}")
    for r in result:
        count = r["end_segment"] - r["start_segment"] + 1
        print(f"  Slide {r['slide']:2d}: segments {r['start_segment']:4d}–{r['end_segment']:4d} ({count} segments)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Align transcript segments to slides using Claude")
    parser.add_argument("--slides", required=True, help="Path to slides.json")
    parser.add_argument("--transcript", required=True, help="Path to transcript.json")
    parser.add_argument("--output", required=True, help="Path to output aligned.json")
    args = parser.parse_args()
    align(args.slides, args.transcript, args.output)
