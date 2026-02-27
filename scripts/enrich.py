import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
  "lecturer_additions": "Det föreläsaren sa utöver bilden – förklaringar, exempel, råd",
  "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"]
}"""


def build_user_prompt(slide: dict, transcript_text: str) -> str:
    return (
        f"BILD (Slide {slide['slide']}):\n{slide['text']}\n\n"
        f"TRANSKRIPTION AV FÖRELÄSARENS ORD:\n{transcript_text}"
    )


def enrich_slide(client: anthropic.Anthropic, slide: dict, transcript_text: str) -> dict:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(slide, transcript_text)}],
    )
    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return raw text if JSON parsing fails
        return {"raw": raw}


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
    except (FileNotFoundError, json.JSONDecodeError):
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

        enriched = enrich_slide(client, slide, transcript_text)
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
