import json
import subprocess
import sys
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from openai import OpenAI

client = anthropic.Anthropic()

# Allow importing from sibling scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.parse_slides import parse_slides
from scripts.align import build_prompt, parse_response
from scripts.enrich import enrich_slide
from scripts.generate_presentation import generate as generate_pptx


def transcribe(audio_path: str) -> list[dict]:
    client = OpenAI()
    print("⏳ Compressing audio...", flush=True)
    mp3_path = audio_path + ".tmp.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", "-b:a", "32k", mp3_path],
        check=True, capture_output=True,
    )
    print("☁️  Uploading to OpenAI Whisper...", flush=True)
    try:
        with open(mp3_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
    finally:
        Path(mp3_path).unlink(missing_ok=True)
    segments = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in result.segments
    ]
    print(f"✅ Transcription done — {len(segments)} segments", flush=True)
    return segments


def align(slides: list[dict], transcript: list[dict]) -> list[dict]:
    print("🔗 Aligning transcript to slides via Claude...", flush=True)
    prompt = build_prompt(slides, transcript)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
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
    print(f"✅ Alignment done — {len(result)} slides mapped", flush=True)
    return result


def enrich(slides: list[dict], transcript: list[dict], alignment: list[dict]) -> list[dict]:
    total = len(alignment)
    done_count = 0
    print(f"✨ Enriching {total} slides via Claude (sequential with retry)...", flush=True)
    slides_by_num = {s["slide"]: s for s in slides}

    def enrich_one(a: dict) -> dict:
        nonlocal done_count
        slide = slides_by_num[a["slide"]]
        text = " ".join(
            seg["text"].strip()
            for seg in transcript[a["start_segment"]: a["end_segment"] + 1]
        )
        for attempt in range(5):
            try:
                enriched = enrich_slide(client, slide, text)
                done_count += 1
                print(f"  ✅ Slide {a['slide']} done ({done_count}/{total})", flush=True)
                return {
                    "slide": a["slide"],
                    "original_text": slide["text"],
                    "start_segment": a["start_segment"],
                    "end_segment": a["end_segment"],
                    **enriched,
                }
            except anthropic.RateLimitError:
                wait = 60 * (attempt + 1)
                print(f"  ⏳ Rate limited on slide {a['slide']}, waiting {wait}s...", flush=True)
                time.sleep(wait)
        raise RuntimeError(f"Failed to enrich slide {a['slide']} after 5 attempts")

    with ThreadPoolExecutor(max_workers=1) as pool:
        results = list(pool.map(enrich_one, alignment))

    results = sorted(results, key=lambda x: x["slide"])
    print(f"✅ Enrichment done", flush=True)
    return results


def run_pipeline(pdf_path: str, audio_path: str, pptx_output_path: str) -> dict:
    # Step 1: Extract slides
    print("📄 Parsing slides from PDF...", flush=True)
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
    print("🎉 Pipeline complete!", flush=True)

    return {
        "slides": slides,
        "transcript": transcript,
        "alignment": alignment,
        "enhanced": enhanced,
        "download_url": f"/download/{Path(pptx_output_path).name}",
    }
