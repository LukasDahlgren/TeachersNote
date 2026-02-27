import json
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db, init_db
from models import Alignment, EnrichedSlide, Lecture, Slide, TranscriptSegment
from pipeline import align, run_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OUT_DIR = Path(__file__).parent.parent / "out"
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
GENERATED_DIR = Path(__file__).parent / "generated"
GENERATED_DIR.mkdir(exist_ok=True)


async def save_lecture_to_db(
    db: AsyncSession,
    name: str,
    slides: list[dict],
    transcript: list[dict],
    alignment: list[dict],
    enhanced: list[dict],
    pptx_path: str | None,
    is_demo: bool = False,
) -> int:
    lecture = Lecture(name=name, is_demo=is_demo, pptx_path=pptx_path)
    db.add(lecture)
    await db.flush()

    db.add_all([
        Slide(lecture_id=lecture.id, slide_number=s["slide"], text=s["text"])
        for s in slides
    ])

    db.add_all([
        TranscriptSegment(
            lecture_id=lecture.id,
            segment_index=i,
            start_time=seg["start"],
            end_time=seg["end"],
            text=seg["text"],
        )
        for i, seg in enumerate(transcript)
    ])

    db.add_all([
        Alignment(
            lecture_id=lecture.id,
            slide_number=a["slide"],
            start_segment=a["start_segment"],
            end_segment=a["end_segment"],
        )
        for a in alignment
    ])

    enhanced_by_slide = {e["slide"]: e for e in enhanced}
    db.add_all([
        EnrichedSlide(
            lecture_id=lecture.id,
            slide_number=slide_num,
            summary=e.get("summary", ""),
            slide_content=e.get("slide_content", ""),
            lecturer_additions=e.get("lecturer_additions", ""),
            key_takeaways=e.get("key_takeaways", []),
        )
        for slide_num, e in enhanced_by_slide.items()
    ])

    await db.commit()
    return lecture.id


async def lecture_to_response(db: AsyncSession, lecture_id: int) -> dict:
    slides_rows = (await db.execute(
        select(Slide).where(Slide.lecture_id == lecture_id).order_by(Slide.slide_number)
    )).scalars().all()

    seg_rows = (await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.lecture_id == lecture_id)
        .order_by(TranscriptSegment.segment_index)
    )).scalars().all()

    align_rows = (await db.execute(
        select(Alignment).where(Alignment.lecture_id == lecture_id).order_by(Alignment.slide_number)
    )).scalars().all()

    return {
        "slides": [{"slide": s.slide_number, "text": s.text} for s in slides_rows],
        "transcript": [
            {"start": s.start_time, "end": s.end_time, "text": s.text} for s in seg_rows
        ],
        "alignment": [
            {"slide": a.slide_number, "start_segment": a.start_segment, "end_segment": a.end_segment}
            for a in align_rows
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/demo")
async def demo(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lecture).where(Lecture.is_demo == True).limit(1))
    existing = result.scalar_one_or_none()

    if existing:
        return await lecture_to_response(db, existing.id)

    slides_path = OUT_DIR / "slides.json"
    transcript_path = OUT_DIR / "transcript.json"
    aligned_path = OUT_DIR / "aligned.json"
    enhanced_path = OUT_DIR / "enhanced.json"

    if not slides_path.exists() or not transcript_path.exists():
        raise HTTPException(status_code=404, detail="Sample data not found in out/")

    with open(slides_path, encoding="utf-8") as f:
        slides = json.load(f)
    with open(transcript_path, encoding="utf-8") as f:
        transcript = json.load(f)

    if aligned_path.exists():
        with open(aligned_path, encoding="utf-8") as f:
            alignment = json.load(f)
    else:
        alignment = await run_in_threadpool(align, slides, transcript)
        with open(aligned_path, "w", encoding="utf-8") as f:
            json.dump(alignment, f, ensure_ascii=False, indent=2)

    enhanced = []
    if enhanced_path.exists():
        with open(enhanced_path, encoding="utf-8") as f:
            enhanced = json.load(f)

    await save_lecture_to_db(
        db=db,
        name="demo",
        slides=slides,
        transcript=transcript,
        alignment=alignment,
        enhanced=enhanced,
        pptx_path=None,
        is_demo=True,
    )

    return {"slides": slides, "transcript": transcript, "alignment": alignment}


@app.get("/download/{filename}")
def download(filename: str):
    path = GENERATED_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.post("/process")
async def process(
    pdf: UploadFile = File(...),
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    pptx_path = GENERATED_DIR / f"{uuid.uuid4()}.pptx"

    with tempfile.TemporaryDirectory(dir=UPLOADS_DIR) as tmp:
        pdf_path = Path(tmp) / "slides.pdf"
        audio_suffix = Path(audio.filename).suffix if audio.filename else ".wav"
        audio_path = Path(tmp) / f"audio{audio_suffix}"

        with open(pdf_path, "wb") as f:
            shutil.copyfileobj(pdf.file, f)
        with open(audio_path, "wb") as f:
            shutil.copyfileobj(audio.file, f)

        try:
            result = await run_in_threadpool(
                run_pipeline, str(pdf_path), str(audio_path), str(pptx_path)
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    lecture_id = await save_lecture_to_db(
        db=db,
        name=pdf.filename or "upload.pdf",
        slides=result["slides"],
        transcript=result["transcript"],
        alignment=result["alignment"],
        enhanced=result["enhanced"],
        pptx_path=str(pptx_path.relative_to(Path(__file__).parent)),
        is_demo=False,
    )

    return {**result, "lecture_id": lecture_id}


@app.get("/lectures")
async def list_lectures(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lecture).order_by(Lecture.created_at.desc()))
    lectures = result.scalars().all()
    return [
        {
            "id": lec.id,
            "name": lec.name,
            "is_demo": lec.is_demo,
            "pptx_path": lec.pptx_path,
            "created_at": lec.created_at.isoformat(),
        }
        for lec in lectures
    ]


@app.get("/lectures/{lecture_id}")
async def get_lecture(lecture_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lecture).where(Lecture.id == lecture_id))
    lecture = result.scalar_one_or_none()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    data = await lecture_to_response(db, lecture_id)
    return {
        **data,
        "lecture_id": lecture.id,
        "name": lecture.name,
        "download_url": f"/download/{Path(lecture.pptx_path).name}" if lecture.pptx_path else None,
    }
