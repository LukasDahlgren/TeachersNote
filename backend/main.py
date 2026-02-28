import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Header, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSessionLocal, get_db, init_db
from media_download import (
    RecordingSourceKind,
    RemoteMediaDownloadError,
    download_remote_media_to_path,
    media_extension_from_url,
    redact_url_for_logs,
    resolve_recording_source,
    validate_remote_media_url,
)
from models import Alignment, EnrichedSlide, Lecture, LectureSave, Slide, TranscriptSegment
from pipeline import (
    enrich_slide_notes,
    generate_presentation_from_enhanced,
    run_pipeline,
)
from scripts.enrich import (
    build_fallback_enrichment,
    is_enriched_payload_invalid,
    normalize_enriched_payload,
)


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

BACKEND_DIR = Path(__file__).parent
UPLOADS_DIR = BACKEND_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
GENERATED_DIR = BACKEND_DIR / "generated"
GENERATED_DIR.mkdir(exist_ok=True)
SOURCE_PDFS_DIR = BACKEND_DIR / "source_pdfs"
SOURCE_PDFS_DIR.mkdir(exist_ok=True)
ARCHIVED_GENERATED_DIR = GENERATED_DIR / "archived"
ARCHIVED_GENERATED_DIR.mkdir(exist_ok=True)

LOGGER = logging.getLogger(__name__)

TERMINAL_JOB_STATUSES = {"done", "error"}
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_ERROR = "error"
JOB_TTL_SECONDS = int(os.getenv("REGENERATE_NOTES_JOB_TTL_SECONDS", "1800"))
UPLOAD_JOB_TTL_SECONDS = int(os.getenv("PROCESS_UPLOAD_JOB_TTL_SECONDS", "1800"))
REGEN_JOB_STORE: dict[str, dict[str, Any]] = {}
ACTIVE_REGEN_JOB_BY_LECTURE: dict[int, str] = {}
REGEN_JOB_LOCK = asyncio.Lock()
UPLOAD_JOB_STORE: dict[str, dict[str, Any]] = {}
ACTIVE_UPLOAD_JOB_ID: str | None = None
UPLOAD_JOB_LOCK = asyncio.Lock()
DEFAULT_USER_ID = "local-dev-user"
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
DEMO_LECTURE_NAME = "DB-lecture-12-2026"


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DISABLE_EXTERNAL_AI = _env_truthy("DISABLE_EXTERNAL_AI", default=False)
if DISABLE_EXTERNAL_AI:
    LOGGER.warning("DISABLE_EXTERNAL_AI=true: regeneration uses deterministic fallback notes only.")

APP_API_KEY = os.getenv("API_KEY")
if not APP_API_KEY:
    raise RuntimeError(
        "API_KEY environment variable is not set. Add it to backend/.env before starting the server."
    )

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_api_key(key: str | None = Depends(_API_KEY_HEADER)) -> None:
    if key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def _require_api_key_or_token(
    key: str | None = Depends(_API_KEY_HEADER),
    token: str | None = Query(default=None),
) -> None:
    """Used for SSE endpoints where EventSource cannot send custom headers."""
    if key == APP_API_KEY or token == APP_API_KEY:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _resolve_user_id(header_value: str | None) -> str:
    value = (header_value or "").strip()
    if not value:
        return DEFAULT_USER_ID
    if not USER_ID_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail="Invalid X-User-Id header. Use 1-128 chars matching [A-Za-z0-9._:-].",
        )
    return value


def get_current_user_id(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> str:
    return _resolve_user_id(x_user_id)


async def get_lecture_or_404(db: AsyncSession, lecture_id: int) -> Lecture:
    result = await db.execute(select(Lecture).where(Lecture.id == lecture_id))
    lecture = result.scalar_one_or_none()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    return lecture


def _join_text(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip()).strip()


def _normalize_naming_token(raw: str, *, uppercase: bool, invalid_chars_pattern: str) -> str:
    value = raw.strip()
    if uppercase:
        value = value.upper()
    value = re.sub(r"[ _]+", "-", value)
    value = re.sub(invalid_chars_pattern, "", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def _normalize_courseid(raw: str) -> str:
    return _normalize_naming_token(
        raw,
        uppercase=True,
        invalid_chars_pattern=r"[^A-Z0-9-]",
    )


def _normalize_lecture(raw: str) -> str:
    return _normalize_naming_token(
        raw,
        uppercase=False,
        invalid_chars_pattern=r"[^A-Za-z0-9-]",
    )


def _normalize_kind(raw: str) -> str:
    value = raw.strip().lower()
    value = re.sub(r"[ _]+", "-", value)
    value = re.sub(r"[^a-z0-9-]", "", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def _validate_year(raw: str) -> str:
    year = raw.strip()
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError("Invalid year: must be exactly 4 digits.")
    return year


def _build_standard_stem(courseid: str, kind: str, lecture: str, year: str) -> str:
    return f"{courseid}-{kind}-{lecture}-{year}"


def _build_unique_generated_paths(stem: str) -> tuple[Path, Path, str]:
    candidate_stem = stem
    counter = 2

    while True:
        pptx_path = GENERATED_DIR / f"{candidate_stem}.pptx"
        pdf_path = SOURCE_PDFS_DIR / f"{candidate_stem}.pdf"
        if not pptx_path.exists() and not pdf_path.exists():
            return pptx_path, pdf_path, candidate_stem

        candidate_stem = f"{stem}-{counter}"
        counter += 1


def _resolve_upload_naming(courseid: str, kind: str, lecture: str, year: str) -> tuple[str, Path, Path]:
    raw_kind = (kind or "").strip()
    if not raw_kind:
        normalized_kind = "lecture"
    else:
        normalized_kind = _normalize_kind(raw_kind)
        if not normalized_kind:
            raise HTTPException(
                status_code=400,
                detail="Invalid kind: provide at least one letter or number.",
            )

    normalized_courseid = _normalize_courseid(courseid)
    if not normalized_courseid:
        raise HTTPException(
            status_code=400,
            detail="Invalid courseid: provide at least one letter or number.",
        )

    normalized_lecture = _normalize_lecture(lecture)
    if not normalized_lecture:
        raise HTTPException(
            status_code=400,
            detail="Invalid lecture: provide at least one letter or number.",
        )

    try:
        normalized_year = _validate_year(year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stem = _build_standard_stem(normalized_courseid, normalized_kind, normalized_lecture, normalized_year)
    pptx_path, saved_pdf_path, final_stem = _build_unique_generated_paths(stem)
    return final_stem, pptx_path, saved_pdf_path


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


def _path_is_within(path: Path, base_dir: Path) -> bool:
    try:
        path.relative_to(base_dir)
        return True
    except ValueError:
        return False


def _resolve_lecture_asset_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (BACKEND_DIR / candidate).resolve()


def _to_backend_relative_path(path: Path) -> str:
    return path.resolve().relative_to(BACKEND_DIR.resolve()).as_posix()


def _path_is_archived_generated(path: Path) -> bool:
    return _path_is_within(path, ARCHIVED_GENERATED_DIR.resolve())


def _resolve_generated_download_path(filename: str) -> Path | None:
    direct = GENERATED_DIR / filename
    if direct.exists() and direct.is_file():
        return direct
    archived = ARCHIVED_GENERATED_DIR / filename
    if archived.exists() and archived.is_file():
        return archived
    return None


def _resolve_pdf_download_path(filename: str) -> Path | None:
    source_pdf = SOURCE_PDFS_DIR / filename
    if source_pdf.exists() and source_pdf.is_file():
        return source_pdf
    return _resolve_generated_download_path(filename)


def _build_collision_safe_destination(target_dir: Path, filename: str, lecture_id: int) -> Path:
    candidate = target_dir / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    base = f"{stem}-lec{lecture_id}"
    candidate = target_dir / f"{base}{suffix}"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = target_dir / f"{base}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _plan_asset_move(
    raw_path: str | None,
    *,
    archive: bool,
    lecture_id: int,
) -> tuple[str | None, tuple[Path, Path] | None]:
    if not raw_path:
        return None, None

    abs_path = _resolve_lecture_asset_path(raw_path)
    if not _path_is_within(abs_path, GENERATED_DIR.resolve()):
        return raw_path, None

    currently_archived = _path_is_archived_generated(abs_path)
    if archive == currently_archived:
        return raw_path, None

    target_root = ARCHIVED_GENERATED_DIR if archive else GENERATED_DIR
    destination = _build_collision_safe_destination(target_root, abs_path.name, lecture_id)
    return _to_backend_relative_path(destination), (abs_path, destination)


def _lecture_file_urls(lecture: Lecture) -> dict[str, str | None]:
    return {
        "download_url": f"/download/{Path(lecture.pptx_path).name}" if lecture.pptx_path else None,
        "pdf_url": f"/pdf/{Path(lecture.pdf_path).name}" if lecture.pdf_path else None,
    }


def _lecture_has_visible_pptx(lecture: Lecture) -> bool:
    # Hide stale lectures that still have a DB row but no backing PPTX asset.
    if not lecture.pptx_path:
        return bool(lecture.is_demo)
    pptx_path = _resolve_lecture_asset_path(lecture.pptx_path)
    return pptx_path.exists() and pptx_path.is_file()


def _lecture_summary_payload(lecture: Lecture, *, is_saved: bool) -> dict[str, Any]:
    return {
        "id": lecture.id,
        "name": lecture.name,
        "is_demo": lecture.is_demo,
        "is_archived": bool(lecture.is_archived),
        "is_saved": is_saved,
        "pptx_path": lecture.pptx_path,
        "pdf_url": _lecture_file_urls(lecture)["pdf_url"],
        "created_at": lecture.created_at.isoformat(),
    }


async def _saved_lecture_ids_for_user(
    db: AsyncSession,
    user_id: str,
    lecture_ids: list[int],
) -> set[int]:
    if not lecture_ids:
        return set()
    result = await db.execute(
        select(LectureSave.lecture_id).where(
            LectureSave.user_id == user_id,
            LectureSave.lecture_id.in_(lecture_ids),
        )
    )
    return {int(lecture_id) for lecture_id in result.scalars().all()}


async def _is_lecture_saved_for_user(db: AsyncSession, user_id: str, lecture_id: int) -> bool:
    result = await db.execute(
        select(LectureSave.id).where(
            LectureSave.user_id == user_id,
            LectureSave.lecture_id == lecture_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def save_lecture_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    lecture_id: int,
    commit: bool = True,
) -> None:
    if await _is_lecture_saved_for_user(db, user_id, lecture_id):
        return
    db.add(LectureSave(user_id=user_id, lecture_id=lecture_id))
    if commit:
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def unsave_lecture_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    lecture_id: int,
) -> None:
    await db.execute(
        delete(LectureSave).where(
            LectureSave.user_id == user_id,
            LectureSave.lecture_id == lecture_id,
        )
    )
    await db.commit()


def _archive_response_payload(lecture: Lecture) -> dict[str, Any]:
    return {
        "id": lecture.id,
        "name": lecture.name,
        "is_archived": bool(lecture.is_archived),
        "pptx_path": lecture.pptx_path,
        "pdf_path": lecture.pdf_path,
        **_lecture_file_urls(lecture),
    }


async def _apply_archive_state(db: AsyncSession, lecture: Lecture, *, archive: bool) -> dict[str, Any]:
    if bool(lecture.is_archived) == archive:
        return _archive_response_payload(lecture)

    next_pptx_path, pptx_move = _plan_asset_move(
        lecture.pptx_path,
        archive=archive,
        lecture_id=lecture.id,
    )
    next_pdf_path, pdf_move = _plan_asset_move(
        lecture.pdf_path,
        archive=archive,
        lecture_id=lecture.id,
    )

    original_state = {
        "pptx_path": lecture.pptx_path,
        "pdf_path": lecture.pdf_path,
        "is_archived": bool(lecture.is_archived),
    }
    moved_assets: list[tuple[Path, Path]] = []

    try:
        for move in [pptx_move, pdf_move]:
            if not move:
                continue
            source_path, destination_path = move
            if not source_path.exists():
                raise RuntimeError(f"Asset file not found: {source_path}")
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(destination_path))
            moved_assets.append((destination_path, source_path))

        lecture.pptx_path = next_pptx_path
        lecture.pdf_path = next_pdf_path
        lecture.is_archived = archive
        await db.commit()
    except Exception as exc:
        await db.rollback()
        for moved_destination, rollback_path in reversed(moved_assets):
            try:
                if moved_destination.exists():
                    rollback_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(moved_destination), str(rollback_path))
            except Exception:
                LOGGER.exception(
                    "Failed to rollback asset move from %s to %s",
                    moved_destination,
                    rollback_path,
                )
        lecture.pptx_path = original_state["pptx_path"]
        lecture.pdf_path = original_state["pdf_path"]
        lecture.is_archived = original_state["is_archived"]

        operation = "archive" if archive else "unarchive"
        raise HTTPException(status_code=500, detail=f"Failed to {operation} lecture: {exc}") from exc

    return _archive_response_payload(lecture)


def _job_public_state(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "lecture_id": job["lecture_id"],
        "status": job["status"],
        "total_slides": job["total_slides"],
        "completed_slides": job["completed_slides"],
        "current_slide": job["current_slide"],
        "regenerated_slides": job["regenerated_slides"],
        "error": job["error"],
        "updated_at": datetime.fromtimestamp(job["updated_at"], tz=timezone.utc).isoformat(),
    }


def _sse_event(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _cleanup_expired_jobs() -> None:
    now = time.time()
    async with REGEN_JOB_LOCK:
        expired = [
            job_id
            for job_id, job in REGEN_JOB_STORE.items()
            if job["status"] in TERMINAL_JOB_STATUSES and (now - float(job["updated_at"])) > JOB_TTL_SECONDS
        ]
        for job_id in expired:
            lecture_id = int(REGEN_JOB_STORE[job_id]["lecture_id"])
            if ACTIVE_REGEN_JOB_BY_LECTURE.get(lecture_id) == job_id:
                ACTIVE_REGEN_JOB_BY_LECTURE.pop(lecture_id, None)
            REGEN_JOB_STORE.pop(job_id, None)


async def _get_job_snapshot(job_id: str) -> dict[str, Any] | None:
    async with REGEN_JOB_LOCK:
        job = REGEN_JOB_STORE.get(job_id)
        if not job:
            return None
        return dict(job)


async def _get_active_job_for_lecture(lecture_id: int) -> dict[str, Any] | None:
    async with REGEN_JOB_LOCK:
        job_id = ACTIVE_REGEN_JOB_BY_LECTURE.get(lecture_id)
        if not job_id:
            return None
        job = REGEN_JOB_STORE.get(job_id)
        if not job or job["status"] in TERMINAL_JOB_STATUSES:
            ACTIVE_REGEN_JOB_BY_LECTURE.pop(lecture_id, None)
            return None
        return dict(job)


async def _create_job(lecture_id: int, total_slides: int) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    now = time.time()
    job = {
        "job_id": job_id,
        "lecture_id": lecture_id,
        "status": JOB_STATUS_QUEUED,
        "total_slides": total_slides,
        "completed_slides": 0,
        "current_slide": None,
        "regenerated_slides": 0,
        "error": None,
        "updated_at": now,
        "version": 0,
    }
    async with REGEN_JOB_LOCK:
        REGEN_JOB_STORE[job_id] = job
        ACTIVE_REGEN_JOB_BY_LECTURE[lecture_id] = job_id
    return dict(job)


async def _update_job(job_id: str, **updates: Any) -> dict[str, Any] | None:
    async with REGEN_JOB_LOCK:
        job = REGEN_JOB_STORE.get(job_id)
        if not job:
            return None
        job.update(updates)
        job["updated_at"] = time.time()
        job["version"] = int(job["version"]) + 1
        if job["status"] in TERMINAL_JOB_STATUSES:
            lecture_id = int(job["lecture_id"])
            if ACTIVE_REGEN_JOB_BY_LECTURE.get(lecture_id) == job_id:
                ACTIVE_REGEN_JOB_BY_LECTURE.pop(lecture_id, None)
        return dict(job)


def _upload_job_public_state(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "current_stage": job["current_stage"],
        "progress_pct": int(job["progress_pct"]),
        "lecture_id": job["lecture_id"],
        "error": job["error"],
        "updated_at": datetime.fromtimestamp(job["updated_at"], tz=timezone.utc).isoformat(),
    }


def _upload_sse_event(event_name: str, payload: dict[str, Any], event_id: int) -> str:
    return f"id: {event_id}\n{_sse_event(event_name, payload)}"


async def _cleanup_expired_upload_jobs() -> None:
    now = time.time()
    async with UPLOAD_JOB_LOCK:
        global ACTIVE_UPLOAD_JOB_ID
        expired = [
            job_id
            for job_id, job in UPLOAD_JOB_STORE.items()
            if job["status"] in TERMINAL_JOB_STATUSES and (now - float(job["updated_at"])) > UPLOAD_JOB_TTL_SECONDS
        ]
        for job_id in expired:
            if ACTIVE_UPLOAD_JOB_ID == job_id:
                ACTIVE_UPLOAD_JOB_ID = None
            UPLOAD_JOB_STORE.pop(job_id, None)


async def _get_upload_job_snapshot(job_id: str) -> dict[str, Any] | None:
    async with UPLOAD_JOB_LOCK:
        job = UPLOAD_JOB_STORE.get(job_id)
        if not job:
            return None
        return dict(job)


async def _get_active_upload_job() -> dict[str, Any] | None:
    async with UPLOAD_JOB_LOCK:
        global ACTIVE_UPLOAD_JOB_ID
        if not ACTIVE_UPLOAD_JOB_ID:
            return None
        job = UPLOAD_JOB_STORE.get(ACTIVE_UPLOAD_JOB_ID)
        if not job or job["status"] in TERMINAL_JOB_STATUSES:
            ACTIVE_UPLOAD_JOB_ID = None
            return None
        return dict(job)


async def _create_upload_job() -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    now = time.time()
    job = {
        "job_id": job_id,
        "status": JOB_STATUS_QUEUED,
        "current_stage": "upload",
        "progress_pct": 0,
        "lecture_id": None,
        "error": None,
        "updated_at": now,
        "version": 0,
        "next_event_id": 1,
        "events": [],
    }
    async with UPLOAD_JOB_LOCK:
        global ACTIVE_UPLOAD_JOB_ID
        UPLOAD_JOB_STORE[job_id] = job
        ACTIVE_UPLOAD_JOB_ID = job_id
    return dict(job)


async def _update_upload_job(
    job_id: str,
    *,
    event_name: str | None = None,
    message: str | None = None,
    **updates: Any,
) -> dict[str, Any] | None:
    async with UPLOAD_JOB_LOCK:
        global ACTIVE_UPLOAD_JOB_ID
        job = UPLOAD_JOB_STORE.get(job_id)
        if not job:
            return None

        if "progress_pct" in updates:
            updates["progress_pct"] = max(0, min(100, int(updates["progress_pct"])))

        job.update(updates)
        job["updated_at"] = time.time()
        job["version"] = int(job["version"]) + 1

        if event_name:
            event_payload = _upload_job_public_state(job)
            if message:
                event_payload["message"] = message

            event_id = int(job["next_event_id"])
            job["next_event_id"] = event_id + 1
            event_payload["event_id"] = event_id

            job["events"].append({
                "id": event_id,
                "event": event_name,
                "payload": event_payload,
            })
            if len(job["events"]) > 2000:
                job["events"] = job["events"][-1000:]

        if job["status"] in TERMINAL_JOB_STATUSES and ACTIVE_UPLOAD_JOB_ID == job_id:
            ACTIVE_UPLOAD_JOB_ID = None

        return dict(job)


async def _get_upload_job_snapshot_and_events(
    job_id: str,
    *,
    after_event_id: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    async with UPLOAD_JOB_LOCK:
        job = UPLOAD_JOB_STORE.get(job_id)
        if not job:
            return None, []

        events = [
            {
                "id": int(evt["id"]),
                "event": str(evt["event"]),
                "payload": dict(evt["payload"]),
            }
            for evt in job["events"]
            if int(evt["id"]) > after_event_id
        ]
        return dict(job), events


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


def _row_to_normalized_enriched_payload(row: EnrichedSlide) -> dict:
    return normalize_enriched_payload({
        "summary": row.summary,
        "slide_content": row.slide_content,
        "lecturer_additions": row.lecturer_additions,
        "key_takeaways": row.key_takeaways,
    })


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


async def generate_notes_for_slide(slide: dict, transcript_text: str) -> dict:
    if DISABLE_EXTERNAL_AI:
        return build_fallback_enrichment(slide, transcript_text)

    notes = await run_in_threadpool(enrich_slide_notes, slide, transcript_text)
    if is_enriched_payload_invalid(notes):
        return build_fallback_enrichment(slide, transcript_text)
    return notes


async def _load_regeneration_context(db: AsyncSession, lecture_id: int) -> dict[str, Any]:
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


async def _run_regenerate_notes_job(job_id: str, lecture_id: int) -> None:
    try:
        await _update_job(job_id, status=JOB_STATUS_RUNNING, error=None)

        async with AsyncSessionLocal() as db:
            context = await _load_regeneration_context(db, lecture_id)
            targets = _build_regeneration_targets(
                context["align_rows"],
                context["enriched_by_slide"],
            )
            total = len(targets)
            await _update_job(
                job_id,
                total_slides=total,
                completed_slides=0,
                current_slide=None,
                regenerated_slides=0,
                status=JOB_STATUS_RUNNING,
                error=None,
            )

            regenerated = 0
            if total == 0:
                await _update_job(
                    job_id,
                    status=JOB_STATUS_DONE,
                    completed_slides=0,
                    regenerated_slides=0,
                    current_slide=None,
                    error=None,
                )
                return

            for idx, target in enumerate(targets, start=1):
                slide_num = target["slide_number"]
                await _update_job(
                    job_id,
                    status=JOB_STATUS_RUNNING,
                    current_slide=slide_num,
                    completed_slides=idx - 1,
                    regenerated_slides=regenerated,
                )

                slide = context["slides_by_num"].get(slide_num, {"slide": slide_num, "text": ""})
                transcript_text = _segment_text_for_alignment(
                    context["segments_by_index"],
                    target["start_segment"],
                    target["end_segment"],
                )
                notes = await generate_notes_for_slide(slide, transcript_text)
                _upsert_enriched_row(
                    db=db,
                    lecture_id=lecture_id,
                    enriched_by_slide=context["enriched_by_slide"],
                    slide_num=slide_num,
                    notes=notes,
                )
                await db.commit()

                regenerated += 1
                await _update_job(
                    job_id,
                    status=JOB_STATUS_RUNNING,
                    current_slide=slide_num,
                    completed_slides=idx,
                    regenerated_slides=regenerated,
                )

            if regenerated > 0:
                await _sync_lecture_pptx_with_enriched_notes(db, lecture_id)

            await _update_job(
                job_id,
                status=JOB_STATUS_DONE,
                completed_slides=total,
                regenerated_slides=regenerated,
                current_slide=None,
                error=None,
            )
    except Exception as exc:
        LOGGER.exception("Regenerate-notes job failed for lecture_id=%s job_id=%s", lecture_id, job_id)
        await _update_job(
            job_id,
            status=JOB_STATUS_ERROR,
            error=str(exc),
            current_slide=None,
        )


async def _run_process_job(
    job_id: str,
    *,
    pdf_path: Path,
    audio_path: Path,
    recording_source: RecordingSourceKind = "file",
    audio_url: str | None = None,
    lecture_name: str,
    pptx_path: Path,
    saved_pdf_path: Path,
    user_id: str,
) -> None:
    loop = asyncio.get_running_loop()
    last_stage: str | None = None

    def emit(stage: str, message: str, progress_pct: int) -> None:
        nonlocal last_stage
        bounded = max(0, min(100, int(progress_pct)))
        if stage != last_stage:
            asyncio.run_coroutine_threadsafe(
                _update_upload_job(
                    job_id,
                    status=JOB_STATUS_RUNNING,
                    current_stage=stage,
                    progress_pct=bounded,
                    event_name="progress",
                    message=message,
                ),
                loop,
            ).result()
            last_stage = stage

        asyncio.run_coroutine_threadsafe(
            _update_upload_job(
                job_id,
                status=JOB_STATUS_RUNNING,
                current_stage=stage,
                progress_pct=bounded,
                event_name="log",
                message=message,
            ),
            loop,
        ).result()

    try:
        if recording_source == "url":
            if not audio_url:
                raise RuntimeError("Missing audio_url for URL recording source.")

            redacted_url = redact_url_for_logs(audio_url)
            await _update_upload_job(
                job_id,
                status=JOB_STATUS_RUNNING,
                current_stage="upload",
                progress_pct=10,
                error=None,
                event_name="progress",
                message=f"Slides uploaded. Downloading recording from URL ({redacted_url})...",
            )
            await run_in_threadpool(download_remote_media_to_path, audio_url, audio_path)
            await _update_upload_job(
                job_id,
                status=JOB_STATUS_RUNNING,
                current_stage="upload",
                progress_pct=18,
                error=None,
                event_name="log",
                message="Recording URL downloaded. Starting processing pipeline...",
            )
        else:
            await _update_upload_job(
                job_id,
                status=JOB_STATUS_RUNNING,
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
        )

        await _update_upload_job(
            job_id,
            status=JOB_STATUS_RUNNING,
            current_stage="persist",
            progress_pct=95,
            event_name="progress",
            message="Persisting results to database...",
        )

        shutil.copy2(pdf_path, saved_pdf_path)

        async with AsyncSessionLocal() as db:
            lecture_id = await save_lecture_to_db(
                db=db,
                name=lecture_name,
                slides=result["slides"],
                transcript=result["transcript"],
                alignment=result["alignment"],
                enhanced=result["enhanced"],
                pptx_path=str(pptx_path.relative_to(BACKEND_DIR)),
                pdf_path=str(saved_pdf_path.relative_to(BACKEND_DIR)),
                is_demo=False,
                saved_user_id=user_id,
            )

        await _update_upload_job(
            job_id,
            status=JOB_STATUS_DONE,
            current_stage="done",
            progress_pct=100,
            lecture_id=lecture_id,
            error=None,
            event_name="done",
            message="Processing complete.",
        )
    except Exception as exc:
        LOGGER.exception("Upload process job failed job_id=%s", job_id)
        await _update_upload_job(
            job_id,
            status=JOB_STATUS_ERROR,
            current_stage="error",
            error=str(exc),
            event_name="error",
            message=str(exc),
        )
        if pptx_path.exists():
            pptx_path.unlink(missing_ok=True)
        if saved_pdf_path.exists():
            saved_pdf_path.unlink(missing_ok=True)
    finally:
        tmp_dir = pdf_path.parent
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def save_lecture_to_db(
    db: AsyncSession,
    name: str,
    slides: list[dict],
    transcript: list[dict],
    alignment: list[dict],
    enhanced: list[dict],
    pptx_path: str | None,
    pdf_path: str | None = None,
    is_demo: bool = False,
    saved_user_id: str | None = None,
) -> int:
    sanitized_enhanced = _sanitize_enhanced_entries(slides, transcript, alignment, enhanced)

    lecture = Lecture(name=name, is_demo=is_demo, pptx_path=pptx_path, pdf_path=pdf_path)
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

    enriched_rows = (await db.execute(
        select(EnrichedSlide).where(EnrichedSlide.lecture_id == lecture_id).order_by(EnrichedSlide.slide_number)
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
        "enhanced": [
            {
                "slide": e.slide_number,
                **_row_to_normalized_enriched_payload(e),
            }
            for e in enriched_rows
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/demo", dependencies=[Depends(_require_api_key)])
async def demo(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Lecture)
        .where(Lecture.name == DEMO_LECTURE_NAME)
        .order_by(Lecture.created_at.desc())
    )
    for lecture in result.scalars().all():
        if _lecture_has_visible_pptx(lecture):
            return await lecture_to_response(db, lecture.id)

    raise HTTPException(
        status_code=404,
        detail=f"Demo lecture '{DEMO_LECTURE_NAME}' not found with a visible PPTX asset.",
    )


@app.get("/pdf/{filename}", dependencies=[Depends(_require_api_key_or_token)])
def serve_pdf(filename: str):
    path = _resolve_pdf_download_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="application/pdf")


@app.get("/download/{filename}", dependencies=[Depends(_require_api_key_or_token)])
def download(filename: str):
    path = _resolve_generated_download_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.post("/process/jobs", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(_require_api_key)])
async def start_process_job(
    pdf: UploadFile = File(...),
    audio: UploadFile | None = File(None),
    audio_url: str | None = Form(None),
    courseid: str = Form(...),
    kind: str = Form("lecture"),
    lecture: str = Form(...),
    year: str = Form(...),
    user_id: str = Depends(get_current_user_id),
):
    await _cleanup_expired_upload_jobs()
    active_job = await _get_active_upload_job()
    if active_job:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Upload processing already in progress",
                "active_job_id": active_job["job_id"],
            },
        )

    lecture_name, pptx_path, saved_pdf_path = _resolve_upload_naming(courseid, kind, lecture, year)
    recording_source, resolved_audio_url = _resolve_recording_source_or_400(audio=audio, audio_url=audio_url)
    validated_audio_url: str | None = None
    if recording_source == "url":
        if not resolved_audio_url:
            raise HTTPException(status_code=400, detail="Missing audio_url for URL recording source.")
        validated_audio_url = _validate_audio_url_or_400(resolved_audio_url)

    job = await _create_upload_job()
    job_id = str(job["job_id"])
    tmp_dir = UPLOADS_DIR / f"process-{job_id}"
    pdf_path = tmp_dir / "slides.pdf"
    if recording_source == "file":
        if audio is None:
            raise HTTPException(status_code=400, detail="Missing audio file for file recording source.")
        audio_suffix = Path(audio.filename).suffix if audio.filename else ".wav"
    else:
        audio_suffix = _audio_suffix_from_url(validated_audio_url or "")
    audio_path = tmp_dir / f"audio{audio_suffix}"

    try:
        tmp_dir.mkdir(parents=True, exist_ok=False)
        with open(pdf_path, "wb") as f:
            shutil.copyfileobj(pdf.file, f)
        if recording_source == "file":
            if audio is None:
                raise RuntimeError("Missing audio file during staging.")
            with open(audio_path, "wb") as f:
                shutil.copyfileobj(audio.file, f)
    except Exception as exc:
        await _update_upload_job(
            job_id,
            status=JOB_STATUS_ERROR,
            current_stage="error",
            error=f"Failed to stage upload files: {exc}",
            event_name="error",
            message=f"Failed to stage upload files: {exc}",
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to stage upload files: {exc}")

    await _update_upload_job(
        job_id,
        status=JOB_STATUS_QUEUED,
        current_stage="upload",
        progress_pct=0,
        error=None,
        event_name="progress",
        message=(
            "Upload received and queued for processing."
            if recording_source == "file"
            else "Upload received and queued for processing. Recording will be downloaded from URL."
        ),
    )

    asyncio.create_task(
        _run_process_job(
            job_id,
            pdf_path=pdf_path,
            audio_path=audio_path,
            recording_source=recording_source,
            audio_url=validated_audio_url,
            lecture_name=lecture_name,
            pptx_path=pptx_path,
            saved_pdf_path=saved_pdf_path,
            user_id=user_id,
        )
    )

    snapshot = await _get_upload_job_snapshot(job_id)
    if not snapshot:
        raise HTTPException(status_code=500, detail="Failed to create processing job")
    return _upload_job_public_state(snapshot)


@app.get("/process/jobs/{job_id}", dependencies=[Depends(_require_api_key)])
async def get_process_job(job_id: str):
    await _cleanup_expired_upload_jobs()
    snapshot = await _get_upload_job_snapshot(job_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Job not found")
    return _upload_job_public_state(snapshot)


@app.get("/process/jobs/{job_id}/events")
async def stream_process_job(
    job_id: str,
    request: Request,
    last_event_id: int | None = None,
    _auth: None = Depends(_require_api_key_or_token),
):
    await _cleanup_expired_upload_jobs()
    snapshot = await _get_upload_job_snapshot(job_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Job not found")

    cursor = max(0, int(last_event_id or 0))
    header_last_event_id = request.headers.get("last-event-id")
    if header_last_event_id:
        try:
            cursor = max(cursor, int(header_last_event_id))
        except ValueError:
            pass

    async def event_stream():
        last_heartbeat = time.monotonic()
        current_cursor = cursor
        while True:
            if await request.is_disconnected():
                break

            job_snapshot, events = await _get_upload_job_snapshot_and_events(
                job_id,
                after_event_id=current_cursor,
            )
            if not job_snapshot:
                payload = {
                    "job_id": job_id,
                    "status": JOB_STATUS_ERROR,
                    "current_stage": "error",
                    "progress_pct": 0,
                    "lecture_id": None,
                    "error": "Job not found",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "event_id": current_cursor + 1,
                }
                yield _upload_sse_event("error", payload, current_cursor + 1)
                break

            if events:
                for evt in events:
                    current_cursor = int(evt["id"])
                    yield _upload_sse_event(evt["event"], evt["payload"], current_cursor)
                    last_heartbeat = time.monotonic()
                    if evt["event"] in TERMINAL_JOB_STATUSES:
                        return
            else:
                if job_snapshot["status"] in TERMINAL_JOB_STATUSES:
                    break
                if (time.monotonic() - last_heartbeat) >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()

            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/process", dependencies=[Depends(_require_api_key)])
async def process(
    pdf: UploadFile = File(...),
    audio: UploadFile | None = File(None),
    audio_url: str | None = Form(None),
    courseid: str = Form(...),
    kind: str = Form("lecture"),
    lecture: str = Form(...),
    year: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    lecture_name, pptx_path, saved_pdf_path = _resolve_upload_naming(courseid, kind, lecture, year)
    recording_source, resolved_audio_url = _resolve_recording_source_or_400(audio=audio, audio_url=audio_url)
    validated_audio_url: str | None = None
    if recording_source == "url":
        if not resolved_audio_url:
            raise HTTPException(status_code=400, detail="Missing audio_url for URL recording source.")
        validated_audio_url = _validate_audio_url_or_400(resolved_audio_url)

    with tempfile.TemporaryDirectory(dir=UPLOADS_DIR) as tmp:
        pdf_path = Path(tmp) / "slides.pdf"
        if recording_source == "file":
            if audio is None:
                raise HTTPException(status_code=400, detail="Missing audio file for file recording source.")
            audio_suffix = Path(audio.filename).suffix if audio.filename else ".wav"
        else:
            audio_suffix = _audio_suffix_from_url(validated_audio_url or "")
        audio_path = Path(tmp) / f"audio{audio_suffix}"

        try:
            with open(pdf_path, "wb") as f:
                shutil.copyfileobj(pdf.file, f)
            if recording_source == "file":
                if audio is None:
                    raise RuntimeError("Missing audio file during staging.")
                with open(audio_path, "wb") as f:
                    shutil.copyfileobj(audio.file, f)
            else:
                if not validated_audio_url:
                    raise RuntimeError("Missing audio_url during staging.")
                await run_in_threadpool(download_remote_media_to_path, validated_audio_url, audio_path)
        except RemoteMediaDownloadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to stage upload files: {exc}") from exc

        try:
            result = await run_in_threadpool(
                run_pipeline, str(pdf_path), str(audio_path), str(pptx_path)
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        shutil.copy2(pdf_path, saved_pdf_path)

    lecture_id = await save_lecture_to_db(
        db=db,
        name=lecture_name,
        slides=result["slides"],
        transcript=result["transcript"],
        alignment=result["alignment"],
        enhanced=result["enhanced"],
        pptx_path=str(pptx_path.relative_to(BACKEND_DIR)),
        pdf_path=str(saved_pdf_path.relative_to(BACKEND_DIR)),
        is_demo=False,
        saved_user_id=user_id,
    )

    return {
        **result,
        "lecture_id": lecture_id,
        "is_archived": False,
        "is_saved": True,
        "pdf_url": f"/pdf/{saved_pdf_path.name}",
    }


@app.get("/lectures", dependencies=[Depends(_require_api_key)])
async def list_lectures(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(Lecture).order_by(Lecture.created_at.desc()))
    lectures = [lecture for lecture in result.scalars().all() if _lecture_has_visible_pptx(lecture)]
    saved_ids = await _saved_lecture_ids_for_user(db, user_id, [int(lecture.id) for lecture in lectures])
    return [_lecture_summary_payload(lecture, is_saved=lecture.id in saved_ids) for lecture in lectures]


@app.get("/lectures/my", dependencies=[Depends(_require_api_key)])
async def list_my_lectures(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(Lecture)
        .join(LectureSave, LectureSave.lecture_id == Lecture.id)
        .where(LectureSave.user_id == user_id)
        .order_by(LectureSave.created_at.desc(), Lecture.created_at.desc())
    )
    lectures = [lecture for lecture in result.scalars().all() if _lecture_has_visible_pptx(lecture)]
    return [_lecture_summary_payload(lecture, is_saved=True) for lecture in lectures]


@app.get("/lectures/{lecture_id}", dependencies=[Depends(_require_api_key)])
async def get_lecture(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    lecture = await get_lecture_or_404(db, lecture_id)
    if not _lecture_has_visible_pptx(lecture):
        raise HTTPException(status_code=404, detail="Lecture file not found")

    data = await lecture_to_response(db, lecture_id)
    return {
        **data,
        "lecture_id": lecture.id,
        "name": lecture.name,
        "is_archived": bool(lecture.is_archived),
        "is_saved": await _is_lecture_saved_for_user(db, user_id, lecture_id),
        **_lecture_file_urls(lecture),
    }


@app.put("/lectures/{lecture_id}/save", dependencies=[Depends(_require_api_key)])
async def save_lecture(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    lecture = await get_lecture_or_404(db, lecture_id)

    await save_lecture_for_user(db, user_id=user_id, lecture_id=lecture_id)
    return _lecture_summary_payload(lecture, is_saved=True)


@app.delete("/lectures/{lecture_id}/save", dependencies=[Depends(_require_api_key)])
async def unsave_lecture(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    lecture = await get_lecture_or_404(db, lecture_id)

    await unsave_lecture_for_user(db, user_id=user_id, lecture_id=lecture_id)
    return _lecture_summary_payload(lecture, is_saved=False)


@app.post("/lectures/{lecture_id}/archive", dependencies=[Depends(_require_api_key)])
async def set_archive_state(
    lecture_id: int,
    archive: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
):
    lecture = await get_lecture_or_404(db, lecture_id)
    return await _apply_archive_state(db, lecture, archive=archive)


@app.post("/lectures/{lecture_id}/regenerate-notes/jobs", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(_require_api_key)])
async def start_regenerate_notes_job(lecture_id: int, db: AsyncSession = Depends(get_db)):
    await _cleanup_expired_jobs()

    await get_lecture_or_404(db, lecture_id)

    active_job = await _get_active_job_for_lecture(lecture_id)
    if active_job:
        return _job_public_state(active_job)

    context = await _load_regeneration_context(db, lecture_id)
    targets = _build_regeneration_targets(context["align_rows"], context["enriched_by_slide"])
    job = await _create_job(lecture_id=lecture_id, total_slides=len(targets))
    asyncio.create_task(_run_regenerate_notes_job(job["job_id"], lecture_id))
    return _job_public_state(job)


@app.get("/lectures/regenerate-notes/jobs/{job_id}", dependencies=[Depends(_require_api_key)])
async def get_regenerate_notes_job(job_id: str):
    await _cleanup_expired_jobs()
    job = await _get_job_snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_public_state(job)


@app.get("/lectures/regenerate-notes/jobs/{job_id}/events")
async def stream_regenerate_notes_job(
    job_id: str,
    request: Request,
    _auth: None = Depends(_require_api_key_or_token),
):
    await _cleanup_expired_jobs()
    job = await _get_job_snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        last_version = -1
        last_heartbeat = time.monotonic()
        while True:
            if await request.is_disconnected():
                break

            snapshot = await _get_job_snapshot(job_id)
            if not snapshot:
                payload = {
                    "job_id": job_id,
                    "lecture_id": 0,
                    "status": JOB_STATUS_ERROR,
                    "total_slides": 0,
                    "completed_slides": 0,
                    "current_slide": None,
                    "regenerated_slides": 0,
                    "error": "Job not found",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                yield _sse_event("error", payload)
                break

            if int(snapshot["version"]) != last_version:
                payload = _job_public_state(snapshot)
                if snapshot["status"] == JOB_STATUS_DONE:
                    event_name = "done"
                elif snapshot["status"] == JOB_STATUS_ERROR:
                    event_name = "error"
                else:
                    event_name = "progress"
                yield _sse_event(event_name, payload)
                last_version = int(snapshot["version"])
                last_heartbeat = time.monotonic()
                if snapshot["status"] in TERMINAL_JOB_STATUSES:
                    break
            elif (time.monotonic() - last_heartbeat) >= 15:
                yield ": keep-alive\n\n"
                last_heartbeat = time.monotonic()

            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/lectures/{lecture_id}/regenerate-notes", dependencies=[Depends(_require_api_key)])
async def regenerate_notes(lecture_id: int, db: AsyncSession = Depends(get_db)):
    await get_lecture_or_404(db, lecture_id)

    context = await _load_regeneration_context(db, lecture_id)
    targets = _build_regeneration_targets(context["align_rows"], context["enriched_by_slide"])

    regenerated_slides = 0
    for target in targets:
        slide_num = target["slide_number"]
        slide = context["slides_by_num"].get(slide_num, {"slide": slide_num, "text": ""})
        transcript_text = _segment_text_for_alignment(
            context["segments_by_index"],
            target["start_segment"],
            target["end_segment"],
        )
        notes = await generate_notes_for_slide(slide, transcript_text)
        _upsert_enriched_row(
            db=db,
            lecture_id=lecture_id,
            enriched_by_slide=context["enriched_by_slide"],
            slide_num=slide_num,
            notes=notes,
        )
        regenerated_slides += 1

    await db.commit()
    if regenerated_slides > 0:
        try:
            await _sync_lecture_pptx_with_enriched_notes(db, lecture_id)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Notes updated, but failed to regenerate PPTX for lecture {lecture_id}: {exc}",
            ) from exc

    refreshed = await lecture_to_response(db, lecture_id)
    return {
        "lecture_id": lecture_id,
        "regenerated_slides": regenerated_slides,
        "enhanced": refreshed["enhanced"],
    }
