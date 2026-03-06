from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from models import (
        Alignment,
        Course,
        EnrichedSlide,
        Lecture,
        Program,
        ProgramCoursePlan,
        Slide,
        StudentCourse,
        StudentProfile,
        TranscriptSegment,
        User,
    )
except ImportError:  # pragma: no cover - package import fallback
    from backend.models import (  # type: ignore[no-redef]
        Alignment,
        Course,
        EnrichedSlide,
        Lecture,
        Program,
        ProgramCoursePlan,
        Slide,
        StudentCourse,
        StudentProfile,
        TranscriptSegment,
        User,
    )

try:
    from scripts.enrich import normalize_enriched_payload
except ImportError:  # pragma: no cover - package import fallback
    from backend.scripts.enrich import normalize_enriched_payload  # type: ignore[no-redef]

try:
    from services.naming import (
        _canonical_course_code,
        _normalize_optional_catalog_code,
        _parse_standard_upload_name,
    )
except ImportError:  # pragma: no cover - package import fallback
    from backend.services.naming import (  # type: ignore[no-redef]
        _canonical_course_code,
        _normalize_optional_catalog_code,
        _parse_standard_upload_name,
    )


def _lecture_file_urls(lecture: Lecture) -> dict[str, str | None]:
    return {
        "download_url": f"/download/{Path(lecture.pptx_path).name}" if lecture.pptx_path else None,
        "pdf_url": f"/pdf/{Path(lecture.pdf_path).name}" if lecture.pdf_path else None,
    }


def _upload_naming_raw_payload(lecture: Lecture) -> dict[str, str | None]:
    return {
        "courseid": (lecture.upload_courseid_raw or "").strip() or None,
        "kind": (lecture.upload_kind_raw or "").strip() or None,
        "lecture": (lecture.upload_lecture_raw or "").strip() or None,
        "year": (lecture.upload_year_raw or "").strip() or None,
    }


def _teachers_note_payload(
    lecture: Lecture,
    *,
    is_saved: bool,
    course_display: str | None,
) -> dict[str, Any]:
    return {
        "id": lecture.id,
        "name": lecture.name,
        "is_demo": lecture.is_demo,
        "is_archived": bool(lecture.is_archived),
        "is_deleted": bool(lecture.is_deleted),
        "is_approved": bool(lecture.is_approved),
        "course_id": lecture.course_id,
        "course_display": course_display,
        "naming_kind": lecture.naming_kind,
        "naming_lecture": lecture.naming_lecture,
        "naming_year": lecture.naming_year,
        "upload_naming_raw": _upload_naming_raw_payload(lecture),
        "uploaded_by": lecture.uploaded_by,
        "is_saved": is_saved,
        "pptx_path": lecture.pptx_path,
        "pdf_url": _lecture_file_urls(lecture)["pdf_url"],
        "created_at": lecture.created_at.isoformat(),
    }


def _lecture_naming_snapshot(lecture: Lecture) -> tuple[str | None, str | None, str | None, str | None]:
    courseid = _normalize_optional_catalog_code(lecture.course_id)
    kind = (lecture.naming_kind or "").strip() or None
    lecture_part = (lecture.naming_lecture or "").strip() or None
    year = (lecture.naming_year or "").strip() or None
    if courseid and kind and lecture_part and year:
        return courseid, kind, lecture_part, year

    parsed = _parse_standard_upload_name(lecture.name)
    if not parsed:
        return courseid, kind, lecture_part, year

    parsed_courseid, parsed_kind, parsed_lecture, parsed_year = parsed
    return (
        courseid or parsed_courseid,
        kind or parsed_kind,
        lecture_part or parsed_lecture,
        year or parsed_year,
    )


def _program_payload(program: Program) -> dict[str, Any]:
    return {
        "id": program.id,
        "code": program.code,
        "name": program.name,
        "is_active": bool(program.is_active),
        "created_at": program.created_at.isoformat(),
        "updated_at": program.updated_at.isoformat(),
    }


def _course_payload(course: Course) -> dict[str, Any]:
    return {
        "id": course.id,
        "code": course.code,
        "display_code": course.display_code,
        "name": course.name,
        "is_active": bool(course.is_active),
        "created_at": course.created_at.isoformat(),
        "updated_at": course.updated_at.isoformat(),
    }


def _program_course_plan_payload(row: ProgramCoursePlan) -> dict[str, Any]:
    snapshot_value = row.snapshot_date.isoformat() if row.snapshot_date else None
    return {
        "id": row.id,
        "program_id": row.program_id,
        "course_id": row.course_id,
        "term_label": row.term_label,
        "group_type": row.group_type,
        "group_label": row.group_label,
        "course_code": row.course_code,
        "course_name_sv": row.course_name_sv,
        "course_url": row.course_url,
        "display_order": row.display_order,
        "snapshot_date": snapshot_value,
    }


def _profile_payload(
    *,
    user_id: str,
    program: Program | None,
    selected_courses: list[Course],
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "program": _program_payload(program) if program else None,
        "selected_courses": [_course_payload(course) for course in selected_courses],
    }


async def _get_program_or_404(db: AsyncSession, program_id: int) -> Program:
    result = await db.execute(select(Program).where(Program.id == program_id))
    program = result.scalar_one_or_none()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found.")
    return program


async def _get_course_or_404(db: AsyncSession, course_id: int) -> Course:
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    return course


async def _get_or_create_student_profile(db: AsyncSession, user_id: str) -> StudentProfile:
    result = await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile:
        return profile
    profile = StudentProfile(user_id=user_id, program_id=None)
    db.add(profile)
    await db.commit()
    return profile


async def _load_profile_payload(db: AsyncSession, user_id: str) -> dict[str, Any]:
    profile_result = await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    profile = profile_result.scalar_one_or_none()
    if not profile:
        return {
            "user_id": user_id,
            "program": None,
            "selected_courses": [],
        }

    program: Program | None = None
    if profile.program_id is not None:
        program_result = await db.execute(select(Program).where(Program.id == profile.program_id))
        program = program_result.scalar_one_or_none()

    selected_result = await db.execute(
        select(Course)
        .join(StudentCourse, StudentCourse.course_id == Course.id)
        .where(StudentCourse.user_id == user_id)
        .order_by(Course.code.asc())
    )
    selected_courses = selected_result.scalars().all()
    return _profile_payload(user_id=user_id, program=program, selected_courses=selected_courses)


def _archive_response_payload(lecture: Lecture) -> dict[str, Any]:
    return {
        "id": lecture.id,
        "name": lecture.name,
        "is_archived": bool(lecture.is_archived),
        "pptx_path": lecture.pptx_path,
        "pdf_path": lecture.pdf_path,
        **_lecture_file_urls(lecture),
    }


def _row_to_normalized_enriched_payload(row: EnrichedSlide) -> dict:
    return normalize_enriched_payload({
        "summary": row.summary,
        "slide_content": row.slide_content,
        "lecturer_additions": row.lecturer_additions,
        "key_takeaways": row.key_takeaways,
    })


async def lecture_to_response(
    db: AsyncSession,
    lecture_id: int,
    *,
    include_transcript: bool = True,
) -> dict:
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
        "slides": [{"slide": s.slide_number, "text": s.text} for s in slides_rows],
        "transcript": (
            [{"start": s.start_time, "end": s.end_time, "text": s.text} for s in seg_rows]
            if include_transcript
            else []
        ),
        "alignment": [
            {"slide": a.slide_number, "start_segment": a.start_segment, "end_segment": a.end_segment}
            for a in align_rows
        ],
        "enhanced": [
            {
                "slide": e.slide_number,
                **_row_to_normalized_enriched_payload(e),
            }
            for e in enriched_rows
        ],
    }


def _user_payload(user: User, *, is_admin: bool) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": is_admin,
        "created_at": user.created_at.isoformat(),
    }


async def _course_display_overrides_by_code(
    db: AsyncSession,
    course_ids: list[str | None],
) -> dict[str, str]:
    normalized_codes = {
        normalized
        for course_id in course_ids
        if (normalized := _canonical_course_code(course_id))
    }
    if not normalized_codes:
        return {}

    result = await db.execute(
        select(Course.code, Course.display_code).where(Course.code.in_(normalized_codes))
    )

    overrides: dict[str, str] = {}
    for course_code, display_code in result.all():
        normalized_display = _normalize_optional_catalog_code(display_code)
        if normalized_display:
            overrides[str(course_code)] = normalized_display
    return overrides


def _resolve_course_display(
    raw_course_id: str | None,
    display_overrides_by_code: dict[str, str],
) -> str | None:
    fallback = (raw_course_id or "").strip()
    if not fallback:
        return None
    override = display_overrides_by_code.get(_canonical_course_code(fallback))
    return override or fallback


__all__ = [
    "_archive_response_payload",
    "_course_display_overrides_by_code",
    "_course_payload",
    "_get_course_or_404",
    "_get_or_create_student_profile",
    "_get_program_or_404",
    "_lecture_file_urls",
    "_lecture_naming_snapshot",
    "_load_profile_payload",
    "_profile_payload",
    "_program_course_plan_payload",
    "_program_payload",
    "_resolve_course_display",
    "_row_to_normalized_enriched_payload",
    "_teachers_note_payload",
    "_upload_naming_raw_payload",
    "_user_payload",
    "lecture_to_response",
]
