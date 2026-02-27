import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from faster_whisper import WhisperModel

# Allow importing from sibling scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.parse_slides import parse_slides
from scripts.align import build_prompt, parse_response
from scripts.enrich import enrich_slide
from scripts.generate_presentation import generate as generate_pptx


def transcribe(audio_path: str) -> list[dict]:
    model = WhisperModel("base", compute_type="int8")
    segments, _ = model.transcribe(audio_path, beam_size=5)
    return [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
    ]


def align(slides: list[dict], transcript: list[dict]) -> list[dict]:
    client = anthropic.Anthropic()
    prompt = build_prompt(slides, transcript)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    boundaries = parse_response(message.content[0].text)
    boundaries.sort(key=lambda x: x["slide"])

    result = []
    for i, b in enumerate(boundaries):
        start = b["start_segment"]
        end = (
            boundaries[i + 1]["start_segment"] - 1
            if i + 1 < len(boundaries)
            else len(transcript) - 1
        )
        result.append({"slide": b["slide"], "start_segment": start, "end_segment": end})
    return result


def enrich(slides: list[dict], transcript: list[dict], alignment: list[dict]) -> list[dict]:
    client = anthropic.Anthropic()
    slides_by_num = {s["slide"]: s for s in slides}

    def enrich_one(a: dict) -> dict:
        slide = slides_by_num[a["slide"]]
        text = " ".join(
            seg["text"].strip()
            for seg in transcript[a["start_segment"]: a["end_segment"] + 1]
        )
        enriched = enrich_slide(client, slide, text)
        return {
            "slide": a["slide"],
            "original_text": slide["text"],
            "start_segment": a["start_segment"],
            "end_segment": a["end_segment"],
            **enriched,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(enrich_one, alignment))

    return sorted(results, key=lambda x: x["slide"])


def run_pipeline(pdf_path: str, audio_path: str, pptx_output_path: str) -> dict:
    # Step 1: Extract slides
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        slides_tmp = f.name
    parse_slides(pdf_path, slides_tmp)
    with open(slides_tmp, encoding="utf-8") as f:
        slides = json.load(f)
    Path(slides_tmp).unlink(missing_ok=True)

    # Step 2: Transcribe audio
    transcript = transcribe(audio_path)

    # Step 3: Align
    alignment = align(slides, transcript)

    # Step 4: Enrich (parallel API calls)
    enhanced = enrich(slides, transcript, alignment)

    # Step 5: Generate PPTX
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as f:
        json.dump(enhanced, f, ensure_ascii=False)
        enhanced_tmp = f.name
    generate_pptx(pdf_path, enhanced_tmp, pptx_output_path)
    Path(enhanced_tmp).unlink(missing_ok=True)

    return {
        "slides": slides,
        "transcript": transcript,
        "alignment": alignment,
        "enhanced": enhanced,
        "download_url": f"/download/{Path(pptx_output_path).name}",
    }
