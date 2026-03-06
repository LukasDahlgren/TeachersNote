from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from db import AsyncSessionLocal
except ImportError:  # pragma: no cover - package import fallback
    from backend.db import AsyncSessionLocal  # type: ignore[no-redef]

try:
    from models import Alignment, Course, EnrichedSlide, Lecture, Slide, TranscriptSegment
except ImportError:  # pragma: no cover - package import fallback
    from backend.models import (  # type: ignore[no-redef]
        Alignment,
        Course,
        EnrichedSlide,
        Lecture,
        Slide,
        TranscriptSegment,
    )

try:
    from pipeline import ENRICH_BATCH_SIZE, enrich_slides_batch_notes, generate_presentation_from_enhanced
except ImportError:  # pragma: no cover - package import fallback
    from backend.pipeline import (  # type: ignore[no-redef]
        ENRICH_BATCH_SIZE,
        enrich_slides_batch_notes,
        generate_presentation_from_enhanced,
    )

try:
    from scripts.enrich import (
        build_fallback_enrichment,
        is_enriched_payload_invalid,
        normalize_enriched_payload,
    )
except ImportError:  # pragma: no cover - package import fallback
    from backend.scripts.enrich import (  # type: ignore[no-redef]
        build_fallback_enrichment,
        is_enriched_payload_invalid,
        normalize_enriched_payload,
    )

try:
    from services.lecture_access import _resolve_lecture_asset_path
    from services.naming import _canonical_course_code, _join_text
    from services.serializers import _row_to_normalized_enriched_payload
except ImportError:  # pragma: no cover - package import fallback
    from backend.services.lecture_access import _resolve_lecture_asset_path  # type: ignore[no-redef]
    from backend.services.naming import _canonical_course_code, _join_text  # type: ignore[no-redef]
    from backend.services.serializers import _row_to_normalized_enriched_payload  # type: ignore[no-redef]


LOGGER = logging.getLogger(__name__)


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DISABLE_EXTERNAL_AI = _env_truthy("DISABLE_EXTERNAL_AI", default=False)


async def _sync_lecture_pptx_with_enriched_notes(db: AsyncSession, lecture_id: int) -> None:
    lecture_row = await db.execute(select(Lecture).where(Lecture.id == lecture_id))
    lecture = lecture_row.scalar_one_or_none()
    if not lecture:
        raise RuntimeError(f"Lecture {lecture_id} not found for PPTX sync.")
    if not lecture.pdf_path:
        raise RuntimeError(f"Lecture {lecture_id} has no PDF path; cannot regenerate PPTX.")
    if not lecture.pptx_path:
        raise RuntimeError(f"Lecture {lecture_id} has no PPTX path; cannot regenerate PPTX.")

    pdf_path = _resolve_lecture_asset_path(lecture.pdf_path)
    pptx_path = _resolve_lecture_asset_path(lecture.pptx_path)
    if not pdf_path.exists():
        raise RuntimeError(f"Source PDF missing for lecture {lecture_id}: {pdf_path}")

    enriched_rows = (await db.execute(
        select(EnrichedSlide)
        .where(EnrichedSlide.lecture_id == lecture_id)
        .order_by(EnrichedSlide.slide_number)
    )).scalars().all()
    enhanced = [
        {"slide": int(row.slide_number), **_row_to_normalized_enriched_payload(row)}
        for row in enriched_rows
    ]

    pptx_path.parent.mkdir(parents=True, exist_ok=True)
    await run_in_threadpool(
        generate_presentation_from_enhanced,
        str(pdf_path),
        enhanced,
        str(pptx_path),
    )


def _segment_text_for_alignment(
    segments_by_index: dict[int, TranscriptSegment],
    start_segment: int,
    end_segment: int,
) -> str:
    texts = []
    for idx in range(start_segment, end_segment + 1):
        seg = segments_by_index.get(idx)
        if seg and seg.text:
            texts.append(seg.text)
    return _join_text(texts)


def _upsert_enriched_row(
    db: AsyncSession,
    lecture_id: int,
    enriched_by_slide: dict[int, EnrichedSlide],
    slide_num: int,
    notes: dict,
) -> None:
    existing = enriched_by_slide.get(slide_num)
    if existing:
        existing.summary = notes["summary"]
        existing.slide_content = notes["slide_content"]
        existing.lecturer_additions = notes["lecturer_additions"]
        existing.key_takeaways = notes["key_takeaways"]
        return

    new_row = EnrichedSlide(
        lecture_id=lecture_id,
        slide_number=slide_num,
        summary=notes["summary"],
        slide_content=notes["slide_content"],
        lecturer_additions=notes["lecturer_additions"],
        key_takeaways=notes["key_takeaways"],
    )
    db.add(new_row)
    enriched_by_slide[slide_num] = new_row


async def generate_notes_for_slide(slide: dict, transcript_text: str, course_context: str | None = None) -> dict:
    notes = await generate_notes_for_slides([(slide, transcript_text)], course_context=course_context)
    if not notes:
        return build_fallback_enrichment(slide, transcript_text)
    return {
        "summary": notes[0]["summary"],
        "slide_content": notes[0]["slide_content"],
        "lecturer_additions": notes[0]["lecturer_additions"],
        "key_takeaways": notes[0]["key_takeaways"],
    }


async def generate_notes_for_slides(
    slides_with_transcripts: list[tuple[dict, str]],
    course_context: str | None = None,
) -> list[dict]:
    if not slides_with_transcripts:
        return []

    if DISABLE_EXTERNAL_AI:
        return [
            {
                "slide": int(slide.get("slide", 0)),
                **build_fallback_enrichment(slide, transcript_text),
            }
            for slide, transcript_text in slides_with_transcripts
        ]

    notes_list = await run_in_threadpool(
        enrich_slides_batch_notes,
        slides_with_transcripts,
        course_context=course_context,
    )
    notes_by_slide = {
        int(note["slide"]): note
        for note in notes_list
        if note.get("slide") is not None
    }
    normalized_results: list[dict] = []
    for slide, transcript_text in slides_with_transcripts:
        slide_num = int(slide.get("slide", 0))
        notes = notes_by_slide.get(slide_num)
        if notes is None or is_enriched_payload_invalid(notes):
            normalized = build_fallback_enrichment(slide, transcript_text)
        else:
            normalized = normalize_enriched_payload(notes)
            if is_enriched_payload_invalid(normalized):
                normalized = build_fallback_enrichment(slide, transcript_text)
        normalized_results.append({"slide": slide_num, **normalized})
    return normalized_results


def _chunk_items(items: list[Any], size: int) -> list[list[Any]]:
    if size <= 1:
        return [[item] for item in items]
    return [items[idx:idx + size] for idx in range(0, len(items), size)]


def _notes_payload_from_batch_entry(entry: dict) -> dict:
    return {
        "summary": entry["summary"],
        "slide_content": entry["slide_content"],
        "lecturer_additions": entry["lecturer_additions"],
        "key_takeaways": entry["key_takeaways"],
    }


async def _lookup_course_context(db: AsyncSession, course_id: str | None) -> str | None:
    normalized = _canonical_course_code(course_id)
    if not normalized:
        return None
    row = (await db.execute(
        select(Course.name, Course.display_code).where(Course.code == normalized)
    )).first()
    if not row:
        return course_id or None
    name, display_code = row
    code_label = (display_code or "").strip() or normalized
    return f"{name} ({code_label})" if name else code_label


async def _load_regeneration_context(db: AsyncSession, lecture_id: int) -> dict[str, Any]:
    lecture_row = (await db.execute(
        select(Lecture.course_id).where(Lecture.id == lecture_id)
    )).first()
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
    enriched_rows = (await db.execute(
        select(EnrichedSlide).where(EnrichedSlide.lecture_id == lecture_id).order_by(EnrichedSlide.slide_number)
    )).scalars().all()

    return {
        "slides_by_num": {s.slide_number: {"slide": s.slide_number, "text": s.text} for s in slides_rows},
        "segments_by_index": {s.segment_index: s for s in seg_rows},
        "align_rows": align_rows,
        "enriched_by_slide": {e.slide_number: e for e in enriched_rows},
        "course_id": lecture_row[0] if lecture_row else None,
    }


def _build_regeneration_targets(
    align_rows: list[Alignment],
    enriched_by_slide: dict[int, EnrichedSlide],
) -> list[dict[str, int]]:
    targets: list[dict[str, int]] = []
    for align_row in align_rows:
        existing = enriched_by_slide.get(align_row.slide_number)
        if existing and not is_enriched_payload_invalid(_row_to_normalized_enriched_payload(existing)):
            continue
        targets.append({
            "slide_number": int(align_row.slide_number),
            "start_segment": int(align_row.start_segment),
            "end_segment": int(align_row.end_segment),
        })
    return targets


async def _run_regenerate_notes_job(
    job_id: str,
    lecture_id: int,
    *,
    update_job: Callable[..., Awaitable[dict[str, Any] | None]],
    async_session_factory: Callable[[], Any] = AsyncSessionLocal,
) -> None:
    try:
        await update_job(job_id, status="running", error=None)

        async with async_session_factory() as db:
            context = await _load_regeneration_context(db, lecture_id)
            course_context = await _lookup_course_context(db, context["course_id"])
            targets = _build_regeneration_targets(
                context["align_rows"],
                context["enriched_by_slide"],
            )
            total = len(targets)
            await update_job(
                job_id,
                total_slides=total,
                completed_slides=0,
                current_slide=None,
                regenerated_slides=0,
                status="running",
                error=None,
            )

            regenerated = 0
            if total == 0:
                await update_job(
                    job_id,
                    status="done",
                    completed_slides=0,
                    regenerated_slides=0,
                    current_slide=None,
                    error=None,
                )
                return

            for batch in _chunk_items(targets, ENRICH_BATCH_SIZE):
                if not batch:
                    continue
                await update_job(
                    job_id,
                    status="running",
                    current_slide=batch[0]["slide_number"],
                    completed_slides=regenerated,
                    regenerated_slides=regenerated,
                )

                batch_payloads: list[tuple[dict[str, int], dict, str]] = []
                for target in batch:
                    slide_num = target["slide_number"]
                    slide = context["slides_by_num"].get(slide_num, {"slide": slide_num, "text": ""})
                    transcript_text = _segment_text_for_alignment(
                        context["segments_by_index"],
                        target["start_segment"],
                        target["end_segment"],
                    )
                    batch_payloads.append((target, slide, transcript_text))

                batch_notes = await generate_notes_for_slides(
                    [(slide, transcript_text) for _, slide, transcript_text in batch_payloads],
                    course_context=course_context,
                )
                notes_by_slide = {int(note["slide"]): note for note in batch_notes}

                for target, slide, transcript_text in batch_payloads:
                    slide_num = target["slide_number"]
                    notes_entry = notes_by_slide.get(slide_num)
                    if notes_entry is None:
                        notes = build_fallback_enrichment(slide, transcript_text)
                    else:
                        notes = _notes_payload_from_batch_entry(notes_entry)
                    _upsert_enriched_row(
                        db=db,
                        lecture_id=lecture_id,
                        enriched_by_slide=context["enriched_by_slide"],
                        slide_num=slide_num,
                        notes=notes,
                    )
                    await db.commit()

                    regenerated += 1
                    await update_job(
                        job_id,
                        status="running",
                        current_slide=slide_num,
                        completed_slides=regenerated,
                        regenerated_slides=regenerated,
                    )

            if regenerated > 0:
                await _sync_lecture_pptx_with_enriched_notes(db, lecture_id)

            await update_job(
                job_id,
                status="done",
                completed_slides=total,
                regenerated_slides=regenerated,
                current_slide=None,
                error=None,
            )
    except Exception as exc:
        LOGGER.exception("Regenerate-notes job failed for lecture_id=%s job_id=%s", lecture_id, job_id)
        await update_job(
            job_id,
            status="error",
            error=str(exc),
            current_slide=None,
        )


__all__ = [
    "_build_regeneration_targets",
    "_chunk_items",
    "_load_regeneration_context",
    "_lookup_course_context",
    "_notes_payload_from_batch_entry",
    "_run_regenerate_notes_job",
    "_segment_text_for_alignment",
    "_sync_lecture_pptx_with_enriched_notes",
    "_upsert_enriched_row",
    "generate_notes_for_slide",
    "generate_notes_for_slides",
]
