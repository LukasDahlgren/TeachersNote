from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from db import AsyncSessionLocal
except ImportError:  # pragma: no cover - package import fallback
    from backend.db import AsyncSessionLocal  # type: ignore[no-redef]

try:
    from media_download import (
        RecordingSourceKind,
        RemoteMediaDownloadError,
        download_remote_media_to_path,
        media_extension_from_url,
        redact_url_for_logs,
        resolve_recording_source,
        validate_remote_media_url,
    )
except ImportError:  # pragma: no cover - package import fallback
    from backend.media_download import (  # type: ignore[no-redef]
        RecordingSourceKind,
        RemoteMediaDownloadError,
        download_remote_media_to_path,
        media_extension_from_url,
        redact_url_for_logs,
        resolve_recording_source,
        validate_remote_media_url,
    )

try:
    from models import Alignment, EnrichedSlide, Lecture, LectureSave, Slide, TranscriptSegment
except ImportError:  # pragma: no cover - package import fallback
    from backend.models import (  # type: ignore[no-redef]
        Alignment,
        EnrichedSlide,
        Lecture,
        LectureSave,
        Slide,
        TranscriptSegment,
    )

try:
    from pipeline import run_pipeline
except ImportError:  # pragma: no cover - package import fallback
    from backend.pipeline import run_pipeline  # type: ignore[no-redef]

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
    from services.naming import _derive_temporary_lecture_name, _join_text, _normalize_lecture
except ImportError:  # pragma: no cover - package import fallback
    from backend.services.naming import (  # type: ignore[no-redef]
        _derive_temporary_lecture_name,
        _join_text,
        _normalize_lecture,
    )


BACKEND_DIR = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger(__name__)


def _resolve_recording_source_or_400(
    *,
    audio: UploadFile | None,
    audio_url: str | None,
) -> tuple[RecordingSourceKind, str | None]:
    try:
        return resolve_recording_source(audio_present=audio is not None, audio_url=audio_url)
    except RemoteMediaDownloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_audio_url_or_400(audio_url: str) -> str:
    try:
        return validate_remote_media_url(audio_url)
    except RemoteMediaDownloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _audio_suffix_from_url(audio_url: str) -> str:
    suffix = media_extension_from_url(audio_url)
    return suffix if suffix else ".wav"


def _build_transcript_text_by_slide(alignment: list[dict], transcript: list[dict]) -> dict[int, str]:
    by_slide: dict[int, str] = {}
    for a in alignment:
        slide_num = int(a["slide"])
        start_segment = int(a["start_segment"])
        end_segment = int(a["end_segment"])
        segs = transcript[start_segment:end_segment + 1]
        by_slide[slide_num] = _join_text([str(seg.get("text", "")) for seg in segs if isinstance(seg, dict)])
    return by_slide


def _sanitize_enhanced_entries(
    slides: list[dict],
    transcript: list[dict],
    alignment: list[dict],
    enhanced: list[dict],
) -> list[dict]:
    slides_by_num = {
        int(s["slide"]): {"slide": int(s["slide"]), "text": str(s.get("text", ""))}
        for s in slides
        if isinstance(s, dict) and "slide" in s
    }
    transcript_by_slide = _build_transcript_text_by_slide(alignment, transcript)
    sanitized_by_slide: dict[int, dict] = {}

    for entry in enhanced:
        if not isinstance(entry, dict):
            continue
        slide_raw = entry.get("slide")
        try:
            slide_num = int(slide_raw)
        except (TypeError, ValueError):
            continue
        normalized = normalize_enriched_payload(entry)
        if is_enriched_payload_invalid(normalized):
            fallback_slide = slides_by_num.get(slide_num, {"slide": slide_num, "text": ""})
            normalized = build_fallback_enrichment(fallback_slide, transcript_by_slide.get(slide_num, ""))
        sanitized_by_slide[slide_num] = {"slide": slide_num, **normalized}

    return [sanitized_by_slide[k] for k in sorted(sanitized_by_slide)]


async def save_lecture_to_db(
    db: AsyncSession,
    name: str,
    slides: list[dict],
    transcript: list[dict],
    alignment: list[dict],
    enhanced: list[dict],
    pptx_path: str | None,
    pdf_path: str | None = None,
    course_id: str | None = None,
    naming_kind: str | None = None,
    naming_lecture: str | None = None,
    naming_year: str | None = None,
    upload_courseid_raw: str | None = None,
    upload_kind_raw: str | None = None,
    upload_lecture_raw: str | None = None,
    upload_year_raw: str | None = None,
    is_demo: bool = False,
    saved_user_id: str | None = None,
    uploaded_by: str | None = None,
    pdf_hash: str | None = None,
) -> int:
    sanitized_enhanced = _sanitize_enhanced_entries(slides, transcript, alignment, enhanced)

    lecture = Lecture(
        name=name,
        is_demo=is_demo,
        is_approved=True,
        course_id=course_id,
        naming_kind=naming_kind,
        naming_lecture=naming_lecture,
        naming_year=naming_year,
        upload_courseid_raw=upload_courseid_raw,
        upload_kind_raw=upload_kind_raw,
        upload_lecture_raw=upload_lecture_raw,
        upload_year_raw=upload_year_raw,
        uploaded_by=uploaded_by,
        pptx_path=pptx_path,
        pdf_path=pdf_path,
        pdf_hash=pdf_hash,
    )
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

    enhanced_by_slide = {e["slide"]: e for e in sanitized_enhanced}
    db.add_all([
        EnrichedSlide(
            lecture_id=lecture.id,
            slide_number=slide_num,
            summary=e["summary"],
            slide_content=e["slide_content"],
            lecturer_additions=e["lecturer_additions"],
            key_takeaways=e["key_takeaways"],
        )
        for slide_num, e in enhanced_by_slide.items()
    ])

    if saved_user_id:
        db.add(LectureSave(user_id=saved_user_id, lecture_id=lecture.id))

    await db.commit()
    return lecture.id


async def update_lecture_enhanced_and_pptx(
    db: AsyncSession,
    lecture_id: int,
    slides: list[dict],
    transcript: list[dict],
    alignment: list[dict],
    enhanced: list[dict],
    pptx_path: str | None,
    name: str | None = None,
) -> None:
    result = await db.execute(select(Lecture).where(Lecture.id == lecture_id))
    lecture = result.scalar_one_or_none()
    if not lecture:
        return
    if pptx_path is not None:
        lecture.pptx_path = pptx_path
    if name is not None:
        lecture.name = name
    await db.execute(delete(EnrichedSlide).where(EnrichedSlide.lecture_id == lecture_id))
    sanitized_enhanced = _sanitize_enhanced_entries(slides, transcript, alignment, enhanced)
    enhanced_by_slide = {e["slide"]: e for e in sanitized_enhanced}
    db.add_all([
        EnrichedSlide(
            lecture_id=lecture_id,
            slide_number=slide_num,
            summary=e["summary"],
            slide_content=e["slide_content"],
            lecturer_additions=e["lecturer_additions"],
            key_takeaways=e["key_takeaways"],
        )
        for slide_num, e in enhanced_by_slide.items()
    ])
    await db.commit()


async def _run_process_job(
    job_id: str,
    *,
    pdf_path: Path,
    audio_path: Path,
    recording_source: RecordingSourceKind = "file",
    audio_url: str | None = None,
    lecture_name: str,
    course_id: str | None,
    naming_kind: str | None,
    naming_lecture: str | None,
    naming_year: str | None,
    upload_courseid_raw: str | None,
    upload_kind_raw: str | None,
    upload_lecture_raw: str | None,
    upload_year_raw: str | None,
    temporary_name_seed: str | None,
    pptx_path: Path,
    saved_pdf_path: Path,
    user_id: str,
    pdf_hash: str | None = None,
    course_context: str | None = None,
    custom_name: str | None = None,
    update_upload_job: Callable[..., Awaitable[dict[str, Any] | None]],
    add_upload_job_raw_event: Callable[[str, str, dict[str, Any]], Awaitable[None]],
    async_session_factory: Callable[[], Any] = AsyncSessionLocal,
) -> None:
    loop = asyncio.get_running_loop()
    last_stage: str | None = None

    def emit(stage: str, message: str, progress_pct: int) -> None:
        nonlocal last_stage
        bounded = max(0, min(100, int(progress_pct)))
        if stage != last_stage:
            asyncio.run_coroutine_threadsafe(
                update_upload_job(
                    job_id,
                    status="running",
                    current_stage=stage,
                    progress_pct=bounded,
                    event_name="progress",
                    message=message,
                ),
                loop,
            ).result()
            last_stage = stage

        asyncio.run_coroutine_threadsafe(
            update_upload_job(
                job_id,
                status="running",
                current_stage=stage,
                progress_pct=bounded,
                event_name="log",
                message=message,
            ),
            loop,
        ).result()

    lecture_id_holder: list[int | None] = [None]

    def on_slides_parsed(count: int) -> None:
        asyncio.run_coroutine_threadsafe(
            update_upload_job(job_id, total_slides=count),
            loop,
        ).result()

    def on_slide_enriched(slide_num: int, payload: dict) -> None:
        asyncio.run_coroutine_threadsafe(
            add_upload_job_raw_event(job_id, "slide_enriched", payload),
            loop,
        ).result()

    def on_pre_enrich(slides: list, transcript: list, alignment: list) -> None:
        early_name = (
            _derive_temporary_lecture_name(slides, temporary_name_seed)
            if temporary_name_seed
            else lecture_name
        )

        async def _create_early() -> None:
            async with async_session_factory() as db:
                lid = await save_lecture_to_db(
                    db=db,
                    name=early_name,
                    slides=slides,
                    transcript=transcript,
                    alignment=alignment,
                    enhanced=[],
                    pptx_path=None,
                    pdf_path=str(saved_pdf_path.relative_to(BACKEND_DIR)),
                    course_id=course_id,
                    naming_kind=naming_kind,
                    naming_lecture=naming_lecture,
                    naming_year=naming_year,
                    upload_courseid_raw=upload_courseid_raw,
                    upload_kind_raw=upload_kind_raw,
                    upload_lecture_raw=upload_lecture_raw,
                    upload_year_raw=upload_year_raw,
                    is_demo=False,
                    saved_user_id=user_id,
                    uploaded_by=user_id,
                    pdf_hash=pdf_hash,
                )
            lecture_id_holder[0] = lid
            await update_upload_job(
                job_id,
                lecture_id=lid,
                event_name="progress",
                message="Lecture added to sidebar. Enriching slide notes...",
            )

        asyncio.run_coroutine_threadsafe(_create_early(), loop).result()

    try:
        if recording_source == "url":
            if not audio_url:
                raise RuntimeError("Missing audio_url for URL recording source.")

            redacted_url = redact_url_for_logs(audio_url)
            await update_upload_job(
                job_id,
                status="running",
                current_stage="upload",
                progress_pct=10,
                error=None,
                event_name="progress",
                message=f"Slides uploaded. Downloading recording from URL ({redacted_url})...",
            )
            await run_in_threadpool(download_remote_media_to_path, audio_url, audio_path)
            await update_upload_job(
                job_id,
                status="running",
                current_stage="upload",
                progress_pct=18,
                error=None,
                event_name="log",
                message="Recording URL downloaded. Starting processing pipeline...",
            )
        else:
            await update_upload_job(
                job_id,
                status="running",
                current_stage="upload",
                progress_pct=10,
                error=None,
                event_name="progress",
                message="Files uploaded. Starting processing pipeline...",
            )

        result = await run_in_threadpool(
            run_pipeline,
            str(pdf_path),
            str(audio_path),
            str(pptx_path),
            emit,
            on_slides_parsed=on_slides_parsed,
            on_slide_enriched=on_slide_enriched,
            on_pre_enrich=on_pre_enrich,
            course_context=course_context,
        )
        resolved_lecture_name = (
            _normalize_lecture(custom_name.strip())[:80]
            if custom_name and custom_name.strip()
            else (
                _derive_temporary_lecture_name(result["slides"], temporary_name_seed)
                if temporary_name_seed
                else lecture_name
            )
        )

        await update_upload_job(
            job_id,
            status="running",
            current_stage="persist",
            progress_pct=95,
            event_name="progress",
            message="Persisting results to database...",
        )

        shutil.copy2(pdf_path, saved_pdf_path)

        async with async_session_factory() as db:
            if lecture_id_holder[0] is not None:
                await update_lecture_enhanced_and_pptx(
                    db=db,
                    lecture_id=lecture_id_holder[0],
                    slides=result["slides"],
                    transcript=result["transcript"],
                    alignment=result["alignment"],
                    enhanced=result["enhanced"],
                    pptx_path=str(pptx_path.relative_to(BACKEND_DIR)),
                    name=resolved_lecture_name,
                )
                lecture_id = lecture_id_holder[0]
            else:
                lecture_id = await save_lecture_to_db(
                    db=db,
                    name=resolved_lecture_name,
                    slides=result["slides"],
                    transcript=result["transcript"],
                    alignment=result["alignment"],
                    enhanced=result["enhanced"],
                    pptx_path=str(pptx_path.relative_to(BACKEND_DIR)),
                    pdf_path=str(saved_pdf_path.relative_to(BACKEND_DIR)),
                    course_id=course_id,
                    naming_kind=naming_kind,
                    naming_lecture=naming_lecture,
                    naming_year=naming_year,
                    upload_courseid_raw=upload_courseid_raw,
                    upload_kind_raw=upload_kind_raw,
                    upload_lecture_raw=upload_lecture_raw,
                    upload_year_raw=upload_year_raw,
                    is_demo=False,
                    saved_user_id=user_id,
                    uploaded_by=user_id,
                    pdf_hash=pdf_hash,
                )

        await update_upload_job(
            job_id,
            status="done",
            current_stage="done",
            progress_pct=100,
            lecture_id=lecture_id,
            error=None,
            event_name="done",
            message="Processing complete.",
        )
    except Exception as exc:
        LOGGER.exception("Upload process job failed job_id=%s", job_id)
        await update_upload_job(
            job_id,
            status="error",
            current_stage="error",
            error=str(exc),
            event_name="error",
            message=str(exc),
        )
        if lecture_id_holder[0] is not None:
            async with async_session_factory() as db:
                lecture = await db.get(Lecture, lecture_id_holder[0])
                if lecture:
                    await db.delete(lecture)
                    await db.commit()
        if pptx_path.exists():
            pptx_path.unlink(missing_ok=True)
        if saved_pdf_path.exists():
            saved_pdf_path.unlink(missing_ok=True)
    finally:
        tmp_dir = pdf_path.parent
        shutil.rmtree(tmp_dir, ignore_errors=True)


__all__ = [
    "_audio_suffix_from_url",
    "_build_transcript_text_by_slide",
    "_resolve_recording_source_or_400",
    "_run_process_job",
    "_sanitize_enhanced_entries",
    "_validate_audio_url_or_400",
    "save_lecture_to_db",
    "update_lecture_enhanced_and_pptx",
]
