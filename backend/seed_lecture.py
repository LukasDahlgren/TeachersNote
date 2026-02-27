"""
Run from the backend/ directory:
  python seed_lecture.py "DB-2026-VT-F3"
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_db, init_db
from models import Alignment, EnrichedSlide, Lecture, Slide, TranscriptSegment

OUT = Path(__file__).parent.parent / "out"

async def seed(name: str):
    await init_db()

    with open(OUT / "slides.json", encoding="utf-8") as f:
        slides = json.load(f)
    with open(OUT / "transcript.json", encoding="utf-8") as f:
        transcript = json.load(f)
    with open(OUT / "aligned.json", encoding="utf-8") as f:
        alignment = json.load(f)
    with open(OUT / "enhanced.json", encoding="utf-8") as f:
        enhanced = json.load(f)

    pptx = OUT / "enhanced_presentation.pptx"

    async for db in get_db():
        lecture = Lecture(name=name, is_demo=False, pptx_path=str(pptx) if pptx.exists() else None)
        db.add(lecture)
        await db.flush()

        db.add_all([Slide(lecture_id=lecture.id, slide_number=s["slide"], text=s["text"]) for s in slides])
        db.add_all([
            TranscriptSegment(lecture_id=lecture.id, segment_index=i, start_time=seg["start"], end_time=seg["end"], text=seg["text"])
            for i, seg in enumerate(transcript)
        ])
        db.add_all([
            Alignment(lecture_id=lecture.id, slide_number=a["slide"], start_segment=a["start_segment"], end_segment=a["end_segment"])
            for a in alignment
        ])
        enhanced_by_slide = {e["slide"]: e for e in enhanced}
        db.add_all([
            EnrichedSlide(
                lecture_id=lecture.id, slide_number=slide_num,
                summary=e.get("summary", ""), slide_content=e.get("slide_content", ""),
                lecturer_additions=e.get("lecturer_additions", ""), key_takeaways=e.get("key_takeaways", []),
            )
            for slide_num, e in enhanced_by_slide.items()
        ])
        await db.commit()
        print(f"✅ Saved '{name}' as lecture id={lecture.id}")
        break

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "DB-2026-VT-F3"
    asyncio.run(seed(name))
