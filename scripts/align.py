import argparse
import json
import re
import anthropic

client = anthropic.Anthropic()


def build_prompt(slides: list[dict], segments: list[dict]) -> str:
    lines = ["SLIDES (presented in order during the lecture):"]
    for slide in slides:
        lines.append(f"\nSlide {slide['slide']}:\n{slide['text']}")

    lines.append("\n\nTRANSCRIPT (numbered segments with timestamps):")
    for i, seg in enumerate(segments):
        lines.append(f"[{i}] {seg['start']:.1f}s: {seg['text'].strip()}")

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
    return "\n".join(lines)


def parse_response(response_text: str) -> list[dict]:
    # Extract JSON array from response (in case Claude adds surrounding text)
    match = re.search(r"\[.*\]", response_text, re.DOTALL)
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
