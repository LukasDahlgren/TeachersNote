import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSessionLocal, get_db, init_db
from catalog_sync import run_catalog_sync
import chatbot as _chatbot
try:
    from jobs.regeneration_jobs import RegenerationJobStore
    from jobs.upload_jobs import UploadJobStore
except ImportError:  # pragma: no cover - package import fallback
    from backend.jobs.regeneration_jobs import RegenerationJobStore
    from backend.jobs.upload_jobs import UploadJobStore
from media_download import (
    RecordingSourceKind,
    RemoteMediaDownloadError,
    download_remote_media_to_path,
    media_extension_from_url,
    redact_url_for_logs,
    resolve_recording_source,
    validate_remote_media_url,
)
from auth import (
    create_access_token,
    get_current_user,
    get_current_user_from_query,
    hash_password,
    verify_password,
    JWT_SECRET_KEY,
)
from models import (
    AdminUser,
    Alignment,
    Course,
    EnrichedSlide,
    Lecture,
    LectureAccess,
    LectureSave,
    Program,
    ProgramCourse,
    ProgramCoursePlan,
    Slide,
    StudentCourse,
    StudentProfile,
    TranscriptSegment,
    User,
)
from pipeline import (
    ENRICH_BATCH_SIZE,
    enrich_slides_batch_notes,
    generate_presentation_from_enhanced,
    run_pipeline,
)
from scripts.enrich import (
    build_fallback_enrichment,
    is_enriched_payload_invalid,
    normalize_enriched_payload,
)
try:
    from services import lecture_access as _lecture_access_service
    from services import naming as _naming_service
    from services import regeneration as _regeneration_service
    from services import serializers as _serializers_service
    from services import upload_workflow as _upload_workflow_service
except ImportError:  # pragma: no cover - package import fallback
    from backend.services import lecture_access as _lecture_access_service
    from backend.services import naming as _naming_service
    from backend.services import regeneration as _regeneration_service
    from backend.services import serializers as _serializers_service
    from backend.services import upload_workflow as _upload_workflow_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _cleanup_orphaned_uploads()
    yield


app = FastAPI(lifespan=lifespan)

_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
REGEN_JOBS = RegenerationJobStore(
    ttl_seconds=JOB_TTL_SECONDS,
    terminal_statuses=TERMINAL_JOB_STATUSES,
)
UPLOAD_JOBS = UploadJobStore(
    ttl_seconds=UPLOAD_JOB_TTL_SECONDS,
    terminal_statuses=TERMINAL_JOB_STATUSES,
)
DEMO_LECTURE_NAME = "IB133N-lecture-14-2026"
ALLOWED_CANONICAL_KINDS = {"lecture", "other"}


async def _cleanup_orphaned_uploads() -> None:
    """Delete DB rows and files left behind by upload jobs interrupted mid-pipeline.

    A lecture with pptx_path=NULL was created by the early-save callback inside the
    pipeline (on_pre_enrich) but never completed.  When the server is starting up
    there are no active processing tasks, so any such row is guaranteed orphaned.
    Cascade deletes on child tables (slides, transcript_segments, alignments,
    enriched_slides, lecture_saves, lecture_access) handle the rest automatically.

    Also removes any stale process-* staging directories in UPLOADS_DIR that were
    not cleaned up due to a previous crash.
    """
    deleted_lectures = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lecture).where(Lecture.pptx_path.is_(None), Lecture.is_demo == False)  # noqa: E712
        )
        orphans = result.scalars().all()
        for lecture in orphans:
            if lecture.pdf_path:
                pdf_file = BACKEND_DIR / lecture.pdf_path
                pdf_file.unlink(missing_ok=True)
            await db.delete(lecture)
            deleted_lectures += 1
        if deleted_lectures:
            await db.commit()

    stale_dirs = list(UPLOADS_DIR.glob("process-*"))
    for stale in stale_dirs:
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)

    if deleted_lectures or stale_dirs:
        LOGGER.info(
            "Startup cleanup: removed %d orphaned lecture(s) and %d stale staging dir(s)",
            deleted_lectures,
            len(stale_dirs),
        )


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DISABLE_EXTERNAL_AI = _env_truthy("DISABLE_EXTERNAL_AI", default=False)
if DISABLE_EXTERNAL_AI:
    LOGGER.warning("DISABLE_EXTERNAL_AI=true: regeneration uses deterministic fallback notes only.")

if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is not set. Add it to backend/.env before starting the server."
    )

ADMIN_SECRET = os.getenv("ADMIN_SECRET")
if not ADMIN_SECRET:
    LOGGER.warning("ADMIN_SECRET is not set. Admin registration will be disabled.")


async def _is_admin(user_id: str, db: AsyncSession) -> bool:
    result = await db.execute(select(AdminUser.id).where(AdminUser.user_id == user_id))
    return result.scalar_one_or_none() is not None


async def get_lecture_or_404(db: AsyncSession, lecture_id: int) -> Lecture:
    result = await db.execute(select(Lecture).where(Lecture.id == lecture_id))
    lecture = result.scalar_one_or_none()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    return lecture


def _non_admin_lecture_access_filter(user_id: str):
    return or_(
        Lecture.uploaded_by == user_id,
        Lecture.id.in_(select(LectureAccess.lecture_id).where(LectureAccess.user_id == user_id)),
    )


async def _user_has_explicit_lecture_access(
    db: AsyncSession,
    *,
    user_id: str,
    lecture_id: int,
) -> bool:
    result = await db.execute(
        select(LectureAccess.lecture_id).where(
            LectureAccess.user_id == user_id,
            LectureAccess.lecture_id == lecture_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def can_view_lecture(
    db: AsyncSession,
    *,
    user_id: str,
    lecture: Lecture,
    is_admin: bool,
) -> bool:
    if is_admin:
        return True
    if bool(lecture.is_deleted):
        return False
    if lecture.uploaded_by == user_id:
        return True
    return await _user_has_explicit_lecture_access(db, user_id=user_id, lecture_id=int(lecture.id))


async def assert_user_can_view_lecture(
    db: AsyncSession,
    *,
    user_id: str,
    lecture: Lecture,
    is_admin: bool,
) -> None:
    if await can_view_lecture(db, user_id=user_id, lecture=lecture, is_admin=is_admin):
        return
    # Intentionally return 404 to avoid revealing lecture visibility state to non-admin users.
    raise HTTPException(status_code=404, detail="Lecture not found")


async def grant_lecture_access_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    lecture_id: int,
    commit: bool = True,
) -> None:
    if await _user_has_explicit_lecture_access(db, user_id=user_id, lecture_id=lecture_id):
        return
    db.add(LectureAccess(user_id=user_id, lecture_id=lecture_id))
    if commit:
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def _require_admin_user_or_403(*, user_id: str, db: AsyncSession) -> None:
    if not await _is_admin(user_id, db):
        raise HTTPException(status_code=403, detail="Admin access required.")


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


def _normalize_catalog_code(raw: str) -> str:
    return _normalize_courseid(raw)


def _normalize_optional_catalog_code(raw: str | None) -> str | None:
    if raw is None:
        return None
    normalized = _normalize_catalog_code(raw)
    return normalized or None


def _require_non_empty_name(raw: str, *, field_name: str) -> str:
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: cannot be empty.")
    return name


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


class UploadNamingResolution(NamedTuple):
    lecture_name: str
    pptx_path: Path
    saved_pdf_path: Path
    courseid: str
    kind: str
    lecture: str
    year: str


class UploadRawNaming(NamedTuple):
    courseid: str | None
    kind: str | None
    lecture: str | None
    year: str | None


class UploadSubmissionResolution(NamedTuple):
    lecture_name: str
    pptx_path: Path
    saved_pdf_path: Path
    courseid: str | None
    kind: str | None
    lecture: str | None
    year: str | None
    raw: UploadRawNaming
    temporary_name_seed: str | None


class StagedLectureAsset(NamedTuple):
    original_path: Path
    staged_path: Path


def _parse_standard_upload_name(name: str) -> tuple[str, str, str, str] | None:
    stem = Path(name).stem.strip()
    if not stem:
        return None

    parts = stem.split("-")
    if len(parts) < 4:
        return None

    maybe_year = parts[-1]
    maybe_suffix = parts[-1] if len(parts) >= 5 else None
    has_numeric_suffix = maybe_suffix is not None and maybe_suffix.isdigit()
    if maybe_year.isdigit() and len(maybe_year) == 4:
        body_parts = parts[:-1]
    elif has_numeric_suffix and parts[-2].isdigit() and len(parts[-2]) == 4:
        maybe_year = parts[-2]
        body_parts = parts[:-2]
    else:
        return None

    if len(body_parts) < 3:
        return None

    courseid = _normalize_courseid(body_parts[0])
    kind = _normalize_kind(body_parts[1])
    lecture = _normalize_lecture("-".join(body_parts[2:]))
    year = maybe_year
    if not courseid or not kind or not lecture:
        return None
    try:
        normalized_year = _validate_year(year)
    except ValueError:
        return None
    return courseid, kind, lecture, normalized_year


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


def _normalize_upload_naming_fields(
    courseid: str,
    kind: str,
    lecture: str,
    year: str,
    *,
    strict_kind: bool = False,
) -> tuple[str, str, str, str]:
    raw_kind = (kind or "").strip()
    if strict_kind:
        normalized_kind = _normalize_kind(raw_kind)
        if not normalized_kind or normalized_kind not in ALLOWED_CANONICAL_KINDS:
            raise HTTPException(
                status_code=400,
                detail="Invalid kind: must be one of lecture, other.",
            )
    elif not raw_kind:
        normalized_kind = "lecture"
    else:
        normalized_kind = _normalize_kind(raw_kind)
        if normalized_kind not in ALLOWED_CANONICAL_KINDS:
            normalized_kind = "other"

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

    return normalized_courseid, normalized_kind, normalized_lecture, normalized_year


def _raw_upload_naming_fields(courseid: str, kind: str, lecture: str, year: str) -> UploadRawNaming:
    return UploadRawNaming(
        courseid=(courseid or "").strip() or None,
        kind=(kind or "").strip() or None,
        lecture=(lecture or "").strip() or None,
        year=(year or "").strip() or None,
    )


def _temporary_upload_stem_from_filename(filename: str | None) -> str:
    raw = Path(filename or "").stem
    normalized = _normalize_lecture(raw) or "upload"
    return f"pending-{normalized[:48]}-{uuid.uuid4().hex[:8]}"


def _temporary_lecture_token_from_slides(slides: list[dict]) -> str | None:
    for slide in slides:
        text = str(slide.get("text") or "").strip()
        if not text:
            continue
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        token = _normalize_lecture(first_line)
        if token:
            return token[:72]
    return None


def _derive_temporary_lecture_name(slides: list[dict], fallback_seed: str | None) -> str:
    fallback = _normalize_lecture(fallback_seed or "") or "upload"
    token = _temporary_lecture_token_from_slides(slides) or fallback
    return f"pending-{token[:72]}-{uuid.uuid4().hex[:6]}"


def _resolve_upload_naming(courseid: str, kind: str, lecture: str, year: str) -> UploadNamingResolution:
    normalized_courseid, normalized_kind, normalized_lecture, normalized_year = _normalize_upload_naming_fields(
        courseid,
        kind,
        lecture,
        year,
    )
    stem = _build_standard_stem(normalized_courseid, normalized_kind, normalized_lecture, normalized_year)
    pptx_path, saved_pdf_path, final_stem = _build_unique_generated_paths(stem)
    return UploadNamingResolution(
        lecture_name=final_stem,
        pptx_path=pptx_path,
        saved_pdf_path=saved_pdf_path,
        courseid=normalized_courseid,
        kind=normalized_kind,
        lecture=normalized_lecture,
        year=normalized_year,
    )


def _resolve_upload_submission_naming(
    *,
    courseid: str | None,
    kind: str | None,
    lecture: str | None,
    year: str | None,
    pdf_filename: str | None,
) -> UploadSubmissionResolution:
    raw = _raw_upload_naming_fields(courseid or "", kind or "", lecture or "", year or "")
    has_any_input = any((raw.courseid, raw.kind, raw.lecture, raw.year))
    has_required_fields = bool(raw.courseid and raw.lecture and raw.year)

    if has_any_input and not has_required_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide all naming fields (courseid, lecture, year) "
                "or leave all naming fields empty for temporary naming."
            ),
        )

    if has_required_fields:
        resolved = _resolve_upload_naming(
            raw.courseid or "",
            raw.kind or "lecture",
            raw.lecture or "",
            raw.year or "",
        )
        return UploadSubmissionResolution(
            lecture_name=resolved.lecture_name,
            pptx_path=resolved.pptx_path,
            saved_pdf_path=resolved.saved_pdf_path,
            courseid=resolved.courseid,
            kind=resolved.kind,
            lecture=resolved.lecture,
            year=resolved.year,
            raw=raw,
            temporary_name_seed=None,
        )

    temp_stem = _temporary_upload_stem_from_filename(pdf_filename)
    pptx_path, saved_pdf_path, final_stem = _build_unique_generated_paths(temp_stem)
    return UploadSubmissionResolution(
        lecture_name=final_stem,
        pptx_path=pptx_path,
        saved_pdf_path=saved_pdf_path,
        courseid=None,
        kind=None,
        lecture=None,
        year=None,
        raw=raw,
        temporary_name_seed=temp_stem,
    )


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


def _lecture_asset_paths_for_permanent_delete(lecture: Lecture) -> list[Path]:
    backend_root = BACKEND_DIR.resolve()
    raw_paths = [lecture.pptx_path, lecture.pdf_path]
    resolved_paths: list[Path] = []
    seen_paths: set[Path] = set()

    for raw_path in raw_paths:
        if not raw_path:
            continue
        resolved = _resolve_lecture_asset_path(raw_path)
        if not _path_is_within(resolved, backend_root):
            raise RuntimeError(f"Refusing to delete lecture asset outside backend dir: {resolved}")
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        resolved_paths.append(resolved)

    return resolved_paths


def _rollback_staged_lecture_assets(staged_assets: list[StagedLectureAsset]) -> None:
    for staged in reversed(staged_assets):
        try:
            if not staged.staged_path.exists():
                continue
            staged.original_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged.staged_path), str(staged.original_path))
        except Exception:
            LOGGER.exception(
                "Failed to restore staged lecture asset from %s to %s",
                staged.staged_path,
                staged.original_path,
            )


async def _assert_lecture_can_be_permanently_deleted(lecture_id: int) -> None:
    await _lecture_access_service._assert_lecture_can_be_permanently_deleted(
        lecture_id,
        get_active_job_for_lecture=_get_active_job_for_lecture,
        get_active_upload_job_for_lecture=_get_active_upload_job_for_lecture,
    )


async def _permanently_delete_lecture(db: AsyncSession, lecture: Lecture) -> None:
    asset_paths = _lecture_asset_paths_for_permanent_delete(lecture)
    stage_dir: Path | None = None
    staged_assets: list[StagedLectureAsset] = []

    try:
        for index, asset_path in enumerate(asset_paths):
            if not asset_path.exists():
                continue
            if asset_path.is_dir() and not asset_path.is_symlink():
                raise RuntimeError(f"Lecture asset is a directory, expected a file: {asset_path}")
            if stage_dir is None:
                stage_dir = Path(tempfile.mkdtemp(prefix=f"lecture-delete-{lecture.id}-", dir=UPLOADS_DIR))
            staged_path = stage_dir / f"{index}-{asset_path.name}"
            shutil.move(str(asset_path), str(staged_path))
            staged_assets.append(StagedLectureAsset(original_path=asset_path, staged_path=staged_path))

        await db.delete(lecture)
        await db.commit()
    except Exception as exc:
        try:
            await db.rollback()
        finally:
            _rollback_staged_lecture_assets(staged_assets)
        raise HTTPException(status_code=500, detail=f"Failed to permanently delete lecture: {exc}") from exc
    finally:
        if stage_dir is not None:
            try:
                shutil.rmtree(stage_dir)
            except Exception:
                LOGGER.exception("Failed to remove staged lecture delete directory: %s", stage_dir)


def _resolve_generated_download_path(filename: str) -> Path | None:
    direct = (GENERATED_DIR / filename).resolve()
    if _path_is_within(direct, GENERATED_DIR.resolve()) and direct.is_file():
        return direct
    archived = (ARCHIVED_GENERATED_DIR / filename).resolve()
    if _path_is_within(archived, ARCHIVED_GENERATED_DIR.resolve()) and archived.is_file():
        return archived
    return None


def _resolve_pdf_download_path(filename: str) -> Path | None:
    source_pdf = (SOURCE_PDFS_DIR / filename).resolve()
    if _path_is_within(source_pdf, SOURCE_PDFS_DIR.resolve()) and source_pdf.is_file():
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
        # Allow in-progress lectures (have pdf but no pptx yet) and demos
        return bool(lecture.pdf_path) or bool(lecture.is_demo)
    pptx_path = _resolve_lecture_asset_path(lecture.pptx_path)
    return pptx_path.exists() and pptx_path.is_file()


def _stored_path_variants(path: Path) -> list[str]:
    variants = {str(path), path.as_posix()}
    try:
        variants.add(_to_backend_relative_path(path))
    except ValueError:
        pass
    return sorted(variants)


async def _find_lecture_for_asset_path(
    db: AsyncSession,
    *,
    path: Path,
    use_pdf_path: bool,
) -> Lecture | None:
    column = Lecture.pdf_path if use_pdf_path else Lecture.pptx_path
    result = await db.execute(
        select(Lecture)
        .where(column.in_(_stored_path_variants(path)))
        .order_by(Lecture.created_at.desc(), Lecture.id.desc())
    )
    return result.scalars().first()


async def _find_reusable_lecture_by_pdf_hash(
    db: AsyncSession,
    *,
    pdf_hash: str | None,
) -> Lecture | None:
    if not pdf_hash:
        return None
    result = await db.execute(
        select(Lecture)
        .where(
            Lecture.pdf_hash == pdf_hash,
            Lecture.is_approved == True,  # noqa: E712
            Lecture.is_deleted == False,  # noqa: E712
            Lecture.is_archived == False,  # noqa: E712
        )
        .order_by(Lecture.created_at.desc(), Lecture.id.desc())
    )
    for lecture in result.scalars().all():
        if _lecture_has_visible_pptx(lecture):
            return lecture
    return None


async def _grant_reused_lecture_access(
    db: AsyncSession,
    *,
    user_id: str,
    lecture_id: int,
) -> None:
    await grant_lecture_access_for_user(
        db,
        user_id=user_id,
        lecture_id=lecture_id,
        commit=False,
    )
    await save_lecture_for_user(
        db,
        user_id=user_id,
        lecture_id=lecture_id,
        commit=False,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()


def _canonical_course_code(raw_course_id: str | None) -> str:
    value = (raw_course_id or "").strip()
    if not value:
        return ""
    return _normalize_catalog_code(value)


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
    return REGEN_JOBS.public_state(job)


def _sse_event(event_name: str, payload: dict[str, Any]) -> str:
    return REGEN_JOBS.sse_event(event_name, payload)


async def _cleanup_expired_jobs() -> None:
    await REGEN_JOBS.cleanup_expired_jobs()


async def _get_job_snapshot(job_id: str) -> dict[str, Any] | None:
    return await REGEN_JOBS.get_job_snapshot(job_id)


async def _assert_user_can_view_regen_job(
    db: AsyncSession,
    *,
    user_id: str,
    job: dict[str, Any],
    is_admin: bool,
) -> None:
    lecture = await get_lecture_or_404(db, int(job["lecture_id"]))
    await assert_user_can_view_lecture(db, user_id=user_id, lecture=lecture, is_admin=is_admin)


async def _get_active_job_for_lecture(lecture_id: int) -> dict[str, Any] | None:
    return await REGEN_JOBS.get_active_job_for_lecture(lecture_id)


async def _create_job(lecture_id: int, total_slides: int) -> dict[str, Any]:
    return await REGEN_JOBS.create_job(lecture_id, total_slides)


async def _update_job(job_id: str, **updates: Any) -> dict[str, Any] | None:
    return await REGEN_JOBS.update_job(job_id, **updates)


def _upload_job_public_state(job: dict[str, Any]) -> dict[str, Any]:
    return UPLOAD_JOBS.public_state(job)


def _upload_sse_event(event_name: str, payload: dict[str, Any], event_id: int) -> str:
    return UPLOAD_JOBS.sse_event(event_name, payload, event_id)


async def _cleanup_expired_upload_jobs() -> None:
    await UPLOAD_JOBS.cleanup_expired_jobs()


async def _get_upload_job_snapshot(job_id: str) -> dict[str, Any] | None:
    return await UPLOAD_JOBS.get_job_snapshot(job_id)


def _assert_user_can_view_upload_job(*, user_id: str, job: dict[str, Any]) -> None:
    UPLOAD_JOBS.assert_user_can_view_job(user_id=user_id, job=job)


async def _get_active_upload_job(user_id: str) -> dict[str, Any] | None:
    return await UPLOAD_JOBS.get_active_job(user_id)


async def _create_upload_job(user_id: str) -> dict[str, Any]:
    return await UPLOAD_JOBS.create_job(user_id)


async def _update_upload_job(
    job_id: str,
    *,
    event_name: str | None = None,
    message: str | None = None,
    **updates: Any,
) -> dict[str, Any] | None:
    return await UPLOAD_JOBS.update_job(
        job_id,
        event_name=event_name,
        message=message,
        **updates,
    )


async def _get_active_upload_job_for_lecture(lecture_id: int) -> dict[str, Any] | None:
    return await UPLOAD_JOBS.get_active_job_for_lecture(lecture_id)


async def _add_upload_job_raw_event(job_id: str, event_name: str, payload: dict[str, Any]) -> None:
    await UPLOAD_JOBS.add_raw_event(job_id, event_name, payload)


async def _get_upload_job_snapshot_and_events(
    job_id: str,
    *,
    after_event_id: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    return await UPLOAD_JOBS.get_job_snapshot_and_events(
        job_id,
        after_event_id=after_event_id,
    )


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


async def _run_regenerate_notes_job(job_id: str, lecture_id: int) -> None:
    await _regeneration_service._run_regenerate_notes_job(
        job_id,
        lecture_id,
        update_job=_update_job,
        async_session_factory=AsyncSessionLocal,
    )


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
) -> None:
    await _upload_workflow_service._run_process_job(
        job_id,
        pdf_path=pdf_path,
        audio_path=audio_path,
        recording_source=recording_source,
        audio_url=audio_url,
        lecture_name=lecture_name,
        course_id=course_id,
        naming_kind=naming_kind,
        naming_lecture=naming_lecture,
        naming_year=naming_year,
        upload_courseid_raw=upload_courseid_raw,
        upload_kind_raw=upload_kind_raw,
        upload_lecture_raw=upload_lecture_raw,
        upload_year_raw=upload_year_raw,
        temporary_name_seed=temporary_name_seed,
        pptx_path=pptx_path,
        saved_pdf_path=saved_pdf_path,
        user_id=user_id,
        pdf_hash=pdf_hash,
        course_context=course_context,
        custom_name=custom_name,
        update_upload_job=_update_upload_job,
        add_upload_job_raw_event=_add_upload_job_raw_event,
        async_session_factory=AsyncSessionLocal,
    )


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
        is_approved=True,  # All uploads are auto-approved; approval workflow disabled
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


# Keep `backend.main` as the stable import surface while delegating internal logic
# to the extracted service modules.
ALLOWED_CANONICAL_KINDS = _naming_service.ALLOWED_CANONICAL_KINDS
UploadNamingResolution = _naming_service.UploadNamingResolution
UploadRawNaming = _naming_service.UploadRawNaming
UploadSubmissionResolution = _naming_service.UploadSubmissionResolution
_join_text = _naming_service._join_text
_normalize_courseid = _naming_service._normalize_courseid
_normalize_catalog_code = _naming_service._normalize_catalog_code
_normalize_optional_catalog_code = _naming_service._normalize_optional_catalog_code
_require_non_empty_name = _naming_service._require_non_empty_name
_normalize_lecture = _naming_service._normalize_lecture
_normalize_kind = _naming_service._normalize_kind
_validate_year = _naming_service._validate_year
_build_standard_stem = _naming_service._build_standard_stem
_parse_standard_upload_name = _naming_service._parse_standard_upload_name
_build_unique_generated_paths = _naming_service._build_unique_generated_paths
_normalize_upload_naming_fields = _naming_service._normalize_upload_naming_fields
_raw_upload_naming_fields = _naming_service._raw_upload_naming_fields
_temporary_upload_stem_from_filename = _naming_service._temporary_upload_stem_from_filename
_temporary_lecture_token_from_slides = _naming_service._temporary_lecture_token_from_slides
_derive_temporary_lecture_name = _naming_service._derive_temporary_lecture_name
_resolve_upload_naming = _naming_service._resolve_upload_naming
_resolve_upload_submission_naming = _naming_service._resolve_upload_submission_naming
_canonical_course_code = _naming_service._canonical_course_code

_is_admin = _lecture_access_service._is_admin
get_lecture_or_404 = _lecture_access_service.get_lecture_or_404
_non_admin_lecture_access_filter = _lecture_access_service._non_admin_lecture_access_filter
_user_has_explicit_lecture_access = _lecture_access_service._user_has_explicit_lecture_access
can_view_lecture = _lecture_access_service.can_view_lecture
assert_user_can_view_lecture = _lecture_access_service.assert_user_can_view_lecture
grant_lecture_access_for_user = _lecture_access_service.grant_lecture_access_for_user
_require_admin_user_or_403 = _lecture_access_service._require_admin_user_or_403
_saved_lecture_ids_for_user = _lecture_access_service._saved_lecture_ids_for_user
save_lecture_for_user = _lecture_access_service.save_lecture_for_user
unsave_lecture_for_user = _lecture_access_service.unsave_lecture_for_user
_path_is_within = _lecture_access_service._path_is_within
_resolve_lecture_asset_path = _lecture_access_service._resolve_lecture_asset_path
_to_backend_relative_path = _lecture_access_service._to_backend_relative_path
_path_is_archived_generated = _lecture_access_service._path_is_archived_generated
StagedLectureAsset = _lecture_access_service.StagedLectureAsset
_lecture_asset_paths_for_permanent_delete = _lecture_access_service._lecture_asset_paths_for_permanent_delete
_rollback_staged_lecture_assets = _lecture_access_service._rollback_staged_lecture_assets
_permanently_delete_lecture = _lecture_access_service._permanently_delete_lecture
_resolve_generated_download_path = _lecture_access_service._resolve_generated_download_path
_resolve_pdf_download_path = _lecture_access_service._resolve_pdf_download_path
_build_collision_safe_destination = _lecture_access_service._build_collision_safe_destination
_plan_asset_move = _lecture_access_service._plan_asset_move
_lecture_has_visible_pptx = _lecture_access_service._lecture_has_visible_pptx
_stored_path_variants = _lecture_access_service._stored_path_variants
_find_lecture_for_asset_path = _lecture_access_service._find_lecture_for_asset_path
_find_reusable_lecture_by_pdf_hash = _lecture_access_service._find_reusable_lecture_by_pdf_hash
_grant_reused_lecture_access = _lecture_access_service._grant_reused_lecture_access
_apply_archive_state = _lecture_access_service._apply_archive_state

_lecture_file_urls = _serializers_service._lecture_file_urls
_upload_naming_raw_payload = _serializers_service._upload_naming_raw_payload
_teachers_note_payload = _serializers_service._teachers_note_payload
_lecture_naming_snapshot = _serializers_service._lecture_naming_snapshot
_program_payload = _serializers_service._program_payload
_course_payload = _serializers_service._course_payload
_program_course_plan_payload = _serializers_service._program_course_plan_payload
_profile_payload = _serializers_service._profile_payload
_get_program_or_404 = _serializers_service._get_program_or_404
_get_course_or_404 = _serializers_service._get_course_or_404
_get_or_create_student_profile = _serializers_service._get_or_create_student_profile
_load_profile_payload = _serializers_service._load_profile_payload
_archive_response_payload = _serializers_service._archive_response_payload
_row_to_normalized_enriched_payload = _serializers_service._row_to_normalized_enriched_payload
lecture_to_response = _serializers_service.lecture_to_response
_course_display_overrides_by_code = _serializers_service._course_display_overrides_by_code
_resolve_course_display = _serializers_service._resolve_course_display

_sync_lecture_pptx_with_enriched_notes = _regeneration_service._sync_lecture_pptx_with_enriched_notes
_segment_text_for_alignment = _regeneration_service._segment_text_for_alignment
_upsert_enriched_row = _regeneration_service._upsert_enriched_row
generate_notes_for_slide = _regeneration_service.generate_notes_for_slide
generate_notes_for_slides = _regeneration_service.generate_notes_for_slides
_chunk_items = _regeneration_service._chunk_items
_notes_payload_from_batch_entry = _regeneration_service._notes_payload_from_batch_entry
_lookup_course_context = _regeneration_service._lookup_course_context
_load_regeneration_context = _regeneration_service._load_regeneration_context
_build_regeneration_targets = _regeneration_service._build_regeneration_targets

_resolve_recording_source_or_400 = _upload_workflow_service._resolve_recording_source_or_400
_validate_audio_url_or_400 = _upload_workflow_service._validate_audio_url_or_400
_audio_suffix_from_url = _upload_workflow_service._audio_suffix_from_url
_build_transcript_text_by_slide = _upload_workflow_service._build_transcript_text_by_slide
_sanitize_enhanced_entries = _upload_workflow_service._sanitize_enhanced_entries
save_lecture_to_db = _upload_workflow_service.save_lecture_to_db
update_lecture_enhanced_and_pptx = _upload_workflow_service.update_lecture_enhanced_and_pptx


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class AuthLoginRequest(BaseModel):
    email: str
    password: str


def _user_payload(user: User, *, is_admin: bool) -> dict[str, Any]:
    return {
        "id": user.id,
        "uuid": user.uuid,
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": is_admin,
        "created_at": user.created_at.isoformat(),
    }


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def auth_register(body: AuthRegisterRequest, db: AsyncSession = Depends(get_db)):
    if "@" not in body.email:
        raise HTTPException(status_code=400, detail="Invalid email address.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    email = body.email.strip().lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=(body.display_name or "").strip() or None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.uuid)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_payload(user, is_admin=False),
    }


@app.post("/auth/login")
async def auth_login(body: AuthLoginRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_access_token(user.uuid)
    is_admin = await _is_admin(user.uuid, db)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_payload(user, is_admin=is_admin),
    }


@app.get("/auth/me")
async def auth_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    is_admin = await _is_admin(current_user.uuid, db)
    return _user_payload(current_user, is_admin=is_admin)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/demo")
async def demo(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await _is_admin(current_user.uuid, db):
        raise HTTPException(status_code=404, detail="Lecture not found")
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


@app.get("/pdf/{filename}")
async def serve_pdf(
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_query),
):
    path = _resolve_pdf_download_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    lecture = await _find_lecture_for_asset_path(db, path=path, use_pdf_path=True)
    if lecture is None:
        lecture = await _find_lecture_for_asset_path(db, path=path, use_pdf_path=False)
    if lecture is None:
        raise HTTPException(status_code=404, detail="File not found")
    admin = await _is_admin(current_user.uuid, db)
    await assert_user_can_view_lecture(db, user_id=current_user.uuid, lecture=lecture, is_admin=admin)
    return FileResponse(path, media_type="application/pdf")


@app.get("/download/{filename}")
async def download(
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_query),
):
    path = _resolve_generated_download_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    lecture = await _find_lecture_for_asset_path(db, path=path, use_pdf_path=False)
    if lecture is None:
        raise HTTPException(status_code=404, detail="File not found")
    admin = await _is_admin(current_user.uuid, db)
    await assert_user_can_view_lecture(db, user_id=current_user.uuid, lecture=lecture, is_admin=admin)
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.post("/process/jobs", status_code=status.HTTP_202_ACCEPTED)
async def start_process_job(
    pdf: UploadFile = File(...),
    audio: UploadFile | None = File(None),
    audio_url: str | None = Form(None),
    courseid: str | None = Form(None),
    kind: str | None = Form(None),
    lecture: str | None = Form(None),
    year: str | None = Form(None),
    course_context: str | None = Form(None),
    custom_name: str | None = Form(None),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    submission_naming = _resolve_upload_submission_naming(
        courseid=courseid,
        kind=kind,
        lecture=lecture,
        year=year,
        pdf_filename=pdf.filename,
    )
    await _cleanup_expired_upload_jobs()
    active_job = await _get_active_upload_job(user_id)
    if active_job:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Upload processing already in progress",
                "active_job_id": active_job["job_id"],
            },
        )

    recording_source, resolved_audio_url = _resolve_recording_source_or_400(audio=audio, audio_url=audio_url)
    validated_audio_url: str | None = None
    if recording_source == "url":
        if not resolved_audio_url:
            raise HTTPException(status_code=400, detail="Missing audio_url for URL recording source.")
        validated_audio_url = _validate_audio_url_or_400(resolved_audio_url)

    pdf_bytes = await pdf.read()
    await pdf.seek(0)
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    async with AsyncSessionLocal() as _dup_db:
        if not await _is_admin(user_id, _dup_db):
            existing = await _find_reusable_lecture_by_pdf_hash(_dup_db, pdf_hash=pdf_hash)
            if existing is not None:
                await _grant_reused_lecture_access(
                    _dup_db,
                    user_id=user_id,
                    lecture_id=int(existing.id),
                )
                job = await _create_upload_job(user_id)
                await _update_upload_job(
                    str(job["job_id"]),
                    status=JOB_STATUS_DONE,
                    current_stage="done",
                    progress_pct=100,
                    lecture_id=int(existing.id),
                    pdf_url=_lecture_file_urls(existing)["pdf_url"],
                    reused_existing=True,
                    error=None,
                    event_name="done",
                    message="Existing lecture unlocked without reprocessing.",
                )
                snapshot = await _get_upload_job_snapshot(str(job["job_id"]))
                if not snapshot:
                    raise HTTPException(status_code=500, detail="Failed to create processing job")
                return _upload_job_public_state(snapshot)

    job = await _create_upload_job(user_id)
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
        # Copy PDF to saved_pdf_path immediately so it's accessible via /pdf/ during live preview
        shutil.copy2(pdf_path, submission_naming.saved_pdf_path)
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
        submission_naming.saved_pdf_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to stage upload files: {exc}")

    await _update_upload_job(
        job_id,
        status=JOB_STATUS_QUEUED,
        current_stage="upload",
        progress_pct=0,
        error=None,
        pdf_url=f"/pdf/{submission_naming.saved_pdf_path.name}",
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
            lecture_name=submission_naming.lecture_name,
            course_id=submission_naming.courseid,
            naming_kind=submission_naming.kind,
            naming_lecture=submission_naming.lecture,
            naming_year=submission_naming.year,
            upload_courseid_raw=submission_naming.raw.courseid,
            upload_kind_raw=submission_naming.raw.kind,
            upload_lecture_raw=submission_naming.raw.lecture,
            upload_year_raw=submission_naming.raw.year,
            temporary_name_seed=submission_naming.temporary_name_seed,
            pptx_path=submission_naming.pptx_path,
            saved_pdf_path=submission_naming.saved_pdf_path,
            user_id=user_id,
            pdf_hash=pdf_hash,
            course_context=(course_context or "").strip() or None,
            custom_name=(custom_name or "").strip() or None,
        )
    )

    snapshot = await _get_upload_job_snapshot(job_id)
    if not snapshot:
        raise HTTPException(status_code=500, detail="Failed to create processing job")
    return _upload_job_public_state(snapshot)


@app.get("/process/jobs/{job_id}")
async def get_process_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    await _cleanup_expired_upload_jobs()
    snapshot = await _get_upload_job_snapshot(job_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_user_can_view_upload_job(user_id=current_user.uuid, job=snapshot)
    return _upload_job_public_state(snapshot)


@app.get("/process/jobs/{job_id}/events")
async def stream_process_job(
    job_id: str,
    request: Request,
    last_event_id: int | None = None,
    current_user: User = Depends(get_current_user_from_query),
):
    await _cleanup_expired_upload_jobs()
    snapshot = await _get_upload_job_snapshot(job_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_user_can_view_upload_job(user_id=current_user.uuid, job=snapshot)

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


@app.post("/process")
async def process(
    pdf: UploadFile = File(...),
    audio: UploadFile | None = File(None),
    audio_url: str | None = Form(None),
    courseid: str | None = Form(None),
    kind: str | None = Form(None),
    lecture: str | None = Form(None),
    year: str | None = Form(None),
    course_context: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    submission_naming = _resolve_upload_submission_naming(
        courseid=courseid,
        kind=kind,
        lecture=lecture,
        year=year,
        pdf_filename=pdf.filename,
    )
    recording_source, resolved_audio_url = _resolve_recording_source_or_400(audio=audio, audio_url=audio_url)
    validated_audio_url: str | None = None
    if recording_source == "url":
        if not resolved_audio_url:
            raise HTTPException(status_code=400, detail="Missing audio_url for URL recording source.")
        validated_audio_url = _validate_audio_url_or_400(resolved_audio_url)

    pdf_hash: str | None = None

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
            pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
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

        if not await _is_admin(user_id, db):
            existing = await _find_reusable_lecture_by_pdf_hash(db, pdf_hash=pdf_hash)
            if existing is not None:
                await _grant_reused_lecture_access(
                    db,
                    user_id=user_id,
                    lecture_id=int(existing.id),
                )
                display_overrides_by_code = await _course_display_overrides_by_code(db, [existing.course_id])
                existing_data = await lecture_to_response(db, int(existing.id))
                return {
                    **existing_data,
                    "lecture_id": int(existing.id),
                    "name": existing.name,
                    "course_id": existing.course_id,
                    "course_display": _resolve_course_display(existing.course_id, display_overrides_by_code),
                    "naming_kind": existing.naming_kind,
                    "naming_lecture": existing.naming_lecture,
                    "naming_year": existing.naming_year,
                    "upload_naming_raw": _upload_naming_raw_payload(existing),
                    "is_archived": bool(existing.is_archived),
                    "is_approved": bool(existing.is_approved),
                    "is_saved": True,
                    "reused_existing": True,
                    **_lecture_file_urls(existing),
                }

        try:
            result = await run_in_threadpool(
                run_pipeline, str(pdf_path), str(audio_path), str(submission_naming.pptx_path),
                course_context=(course_context or "").strip() or None,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        shutil.copy2(pdf_path, submission_naming.saved_pdf_path)

    resolved_lecture_name = (
        _normalize_lecture(custom_name.strip())[:80]
        if custom_name and custom_name.strip()
        else (
            _derive_temporary_lecture_name(result["slides"], submission_naming.temporary_name_seed)
            if submission_naming.temporary_name_seed
            else submission_naming.lecture_name
        )
    )

    lecture_id = await save_lecture_to_db(
        db=db,
        name=resolved_lecture_name,
        slides=result["slides"],
        transcript=result["transcript"],
        alignment=result["alignment"],
        enhanced=result["enhanced"],
        pptx_path=str(submission_naming.pptx_path.relative_to(BACKEND_DIR)),
        pdf_path=str(submission_naming.saved_pdf_path.relative_to(BACKEND_DIR)),
        course_id=submission_naming.courseid,
        naming_kind=submission_naming.kind,
        naming_lecture=submission_naming.lecture,
        naming_year=submission_naming.year,
        upload_courseid_raw=submission_naming.raw.courseid,
        upload_kind_raw=submission_naming.raw.kind,
        upload_lecture_raw=submission_naming.raw.lecture,
        upload_year_raw=submission_naming.raw.year,
        is_demo=False,
        saved_user_id=user_id,
        uploaded_by=user_id,
        pdf_hash=pdf_hash,
    )

    return {
        **result,
        "lecture_id": lecture_id,
        "course_id": submission_naming.courseid,
        "naming_kind": submission_naming.kind,
        "naming_lecture": submission_naming.lecture,
        "naming_year": submission_naming.year,
        "is_archived": False,
        "is_approved": True,
        "is_saved": True,
        "reused_existing": False,
        "pdf_url": f"/pdf/{submission_naming.saved_pdf_path.name}",
    }


@app.get("/lectures")
async def list_lectures(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    admin = await _is_admin(user_id, db)
    if admin:
        visibility_filter = Lecture.is_deleted == False
    else:
        visibility_filter = (Lecture.is_deleted == False) & _non_admin_lecture_access_filter(user_id)
    result = await db.execute(select(Lecture).where(visibility_filter).order_by(Lecture.created_at.desc()))
    lectures = [lecture for lecture in result.scalars().all() if _lecture_has_visible_pptx(lecture)]
    saved_ids = await _saved_lecture_ids_for_user(db, user_id, [int(lecture.id) for lecture in lectures])
    display_overrides_by_code = await _course_display_overrides_by_code(
        db,
        [lecture.course_id for lecture in lectures],
    )
    return [
        _teachers_note_payload(
            lecture,
            is_saved=lecture.id in saved_ids,
            course_display=_resolve_course_display(lecture.course_id, display_overrides_by_code),
        )
        for lecture in lectures
    ]


@app.get("/lectures/my")
async def list_my_lectures(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    admin = await _is_admin(user_id, db)
    query = (
        select(Lecture)
        .join(LectureSave, LectureSave.lecture_id == Lecture.id)
        .where(LectureSave.user_id == user_id)
        .where(Lecture.is_deleted == False)
    )
    if not admin:
        query = query.where(_non_admin_lecture_access_filter(user_id))
    result = await db.execute(query.order_by(LectureSave.created_at.desc(), Lecture.created_at.desc()))
    lectures = [lecture for lecture in result.scalars().all() if _lecture_has_visible_pptx(lecture)]
    display_overrides_by_code = await _course_display_overrides_by_code(
        db,
        [lecture.course_id for lecture in lectures],
    )
    return [
        _teachers_note_payload(
            lecture,
            is_saved=True,
            course_display=_resolve_course_display(lecture.course_id, display_overrides_by_code),
        )
        for lecture in lectures
    ]


@app.get("/lectures/deleted")
async def list_deleted_lectures(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    return []


@app.get("/lectures/{lecture_id}")
async def get_lecture(
    lecture_id: int,
    include_transcript: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    lecture = await get_lecture_or_404(db, lecture_id)
    admin = await _is_admin(user_id, db)
    await assert_user_can_view_lecture(db, user_id=user_id, lecture=lecture, is_admin=admin)
    if not _lecture_has_visible_pptx(lecture):
        raise HTTPException(status_code=404, detail="Lecture file not found")

    data = await lecture_to_response(db, lecture_id, include_transcript=include_transcript)
    display_overrides_by_code = await _course_display_overrides_by_code(db, [lecture.course_id])
    return {
        **data,
        "lecture_id": lecture.id,
        "name": lecture.name,
        "course_id": lecture.course_id,
        "course_display": _resolve_course_display(lecture.course_id, display_overrides_by_code),
        "naming_kind": lecture.naming_kind,
        "naming_lecture": lecture.naming_lecture,
        "naming_year": lecture.naming_year,
        "upload_naming_raw": _upload_naming_raw_payload(lecture),
        "is_archived": bool(lecture.is_archived),
        "is_saved": await _is_lecture_saved_for_user(db, user_id, lecture_id),
        **_lecture_file_urls(lecture),
    }


@app.put("/lectures/{lecture_id}/save")
async def save_lecture(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    lecture = await get_lecture_or_404(db, lecture_id)
    admin = await _is_admin(user_id, db)
    await assert_user_can_view_lecture(db, user_id=user_id, lecture=lecture, is_admin=admin)

    await save_lecture_for_user(db, user_id=user_id, lecture_id=lecture_id)
    display_overrides_by_code = await _course_display_overrides_by_code(db, [lecture.course_id])
    return _teachers_note_payload(
        lecture,
        is_saved=True,
        course_display=_resolve_course_display(lecture.course_id, display_overrides_by_code),
    )


@app.delete("/lectures/{lecture_id}/save")
async def unsave_lecture(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    lecture = await get_lecture_or_404(db, lecture_id)
    admin = await _is_admin(user_id, db)
    await assert_user_can_view_lecture(db, user_id=user_id, lecture=lecture, is_admin=admin)

    await unsave_lecture_for_user(db, user_id=user_id, lecture_id=lecture_id)
    display_overrides_by_code = await _course_display_overrides_by_code(db, [lecture.course_id])
    return _teachers_note_payload(
        lecture,
        is_saved=False,
        course_display=_resolve_course_display(lecture.course_id, display_overrides_by_code),
    )


@app.post("/lectures/{lecture_id}/archive")
async def set_archive_state(
    lecture_id: int,
    archive: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    lecture = await get_lecture_or_404(db, lecture_id)
    return await _apply_archive_state(db, lecture, archive=archive)


@app.post("/lectures/{lecture_id}/trash")
async def trash_lecture(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    lecture = await get_lecture_or_404(db, lecture_id)
    await _assert_lecture_can_be_permanently_deleted(int(lecture.id))
    deleted_id = int(lecture.id)
    await _permanently_delete_lecture(db, lecture)
    return {"id": deleted_id, "is_deleted": True}


@app.post("/lectures/{lecture_id}/restore")
async def restore_lecture(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    raise HTTPException(status_code=410, detail="Lectures are permanently deleted and cannot be restored.")


class AdminRegisterRequest(BaseModel):
    secret: str


class ProgramCreateRequest(BaseModel):
    code: str
    name: str
    is_active: bool = True


class ProgramUpdateRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    is_active: bool | None = None


class CourseCreateRequest(BaseModel):
    code: str
    display_code: str | None = None
    name: str
    is_active: bool = True


class CourseUpdateRequest(BaseModel):
    code: str | None = None
    display_code: str | None = None
    name: str | None = None
    is_active: bool | None = None


class ProfileProgramUpdateRequest(BaseModel):
    program_id: int | None = None


class ProfileCoursesUpdateRequest(BaseModel):
    course_ids: list[int]


class CatalogSyncRequest(BaseModel):
    snapshot_date: str | None = None
    dry_run: bool = False


class ApproveLectureRequest(BaseModel):
    courseid: str
    kind: str
    lecture: str
    year: str


@app.get("/profile")
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    return await _load_profile_payload(db, user_id)


@app.put("/profile/program")
async def set_profile_program(
    body: ProfileProgramUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    if body.program_id is not None:
        program = await _get_program_or_404(db, body.program_id)
        if not bool(program.is_active):
            raise HTTPException(status_code=400, detail="Program is inactive.")

    profile = await _get_or_create_student_profile(db, user_id)
    profile.program_id = body.program_id
    await db.commit()
    return await _load_profile_payload(db, user_id)


@app.put("/profile/courses")
async def set_profile_courses(
    body: ProfileCoursesUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    requested_ids = list(dict.fromkeys(body.course_ids))
    if any(course_id <= 0 for course_id in requested_ids):
        raise HTTPException(status_code=400, detail="course_ids must contain positive integers.")

    if requested_ids:
        result = await db.execute(
            select(Course).where(Course.id.in_(requested_ids), Course.is_active == True)
        )
        active_courses = result.scalars().all()
        active_ids = {int(course.id) for course in active_courses}
        missing_ids = [course_id for course_id in requested_ids if course_id not in active_ids]
        if missing_ids:
            missing_str = ",".join(str(course_id) for course_id in missing_ids)
            raise HTTPException(
                status_code=400,
                detail=f"Unknown or inactive course ids: {missing_str}",
            )

    await _get_or_create_student_profile(db, user_id)
    await db.execute(delete(StudentCourse).where(StudentCourse.user_id == user_id))
    for course_id in requested_ids:
        db.add(StudentCourse(user_id=user_id, course_id=course_id))
    await db.commit()
    return await _load_profile_payload(db, user_id)


@app.get("/profile/course-options")
async def get_profile_course_options(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    admin = await _is_admin(user_id, db)
    profile_result = await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    profile = profile_result.scalar_one_or_none()

    all_courses_query = select(Course).order_by(Course.code.asc())
    if not admin:
        all_courses_query = all_courses_query.where(Course.is_active == True)
    all_courses_result = await db.execute(all_courses_query)
    all_courses = all_courses_result.scalars().all()

    programs_query = select(Program).order_by(Program.code.asc())
    if not admin:
        programs_query = programs_query.where(Program.is_active == True)
    programs_result = await db.execute(programs_query)
    programs = programs_result.scalars().all()

    grouped_courses_query = (
        select(Program, Course)
        .join(ProgramCourse, ProgramCourse.program_id == Program.id)
        .join(Course, ProgramCourse.course_id == Course.id)
        .order_by(Program.code.asc(), Course.code.asc())
    )
    if not admin:
        grouped_courses_query = grouped_courses_query.where(
            Program.is_active == True,
            Course.is_active == True,
        )
    grouped_courses_result = await db.execute(grouped_courses_query)
    grouped_courses_rows = grouped_courses_result.all()
    grouped_courses_by_program: dict[int, list[Course]] = {}
    for mapped_program, mapped_course in grouped_courses_rows:
        grouped_courses_by_program.setdefault(int(mapped_program.id), []).append(mapped_course)

    program_course_groups: list[dict[str, Any]] = []
    for item in programs:
        grouped_courses = grouped_courses_by_program.get(int(item.id), [])
        program_course_groups.append(
            {
                "program": _program_payload(item),
                "courses": [_course_payload(course) for course in grouped_courses],
            }
        )

    program: Program | None = None
    program_courses: list[Course] = []
    if profile and profile.program_id is not None:
        program_result = await db.execute(select(Program).where(Program.id == profile.program_id))
        program = program_result.scalar_one_or_none()
        if program:
            program_courses_query = (
                select(Course)
                .join(ProgramCourse, ProgramCourse.course_id == Course.id)
                .where(ProgramCourse.program_id == program.id)
                .order_by(Course.code.asc())
            )
            if not admin:
                program_courses_query = program_courses_query.where(Course.is_active == True)
            program_courses_result = await db.execute(program_courses_query)
            program_courses = program_courses_result.scalars().all()

    return {
        "program": _program_payload(program) if program else None,
        "programs": [_program_payload(item) for item in programs],
        "all_courses": [_course_payload(course) for course in all_courses],
        "program_courses": [_course_payload(course) for course in program_courses],
        "program_course_groups": program_course_groups,
    }


@app.get("/programs")
async def list_public_programs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Program).where(Program.is_active == True).order_by(Program.code.asc()))
    return [_program_payload(program) for program in result.scalars().all()]


@app.get("/admin/programs")
async def list_programs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    result = await db.execute(select(Program).order_by(Program.code.asc()))
    return [_program_payload(program) for program in result.scalars().all()]


@app.post("/admin/programs")
async def create_program(
    body: ProgramCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    code = _normalize_catalog_code(body.code)
    if not code:
        raise HTTPException(status_code=400, detail="Invalid code: use A-Z, 0-9, or '-'.")
    name = _require_non_empty_name(body.name, field_name="name")

    program = Program(code=code, name=name, is_active=bool(body.is_active))
    db.add(program)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Program code already exists.") from exc
    await db.refresh(program)
    return _program_payload(program)


@app.patch("/admin/programs/{program_id}")
async def update_program(
    program_id: int,
    body: ProgramUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    program = await _get_program_or_404(db, program_id)

    if body.code is None and body.name is None and body.is_active is None:
        raise HTTPException(status_code=400, detail="Provide at least one field to update.")

    if body.code is not None:
        code = _normalize_catalog_code(body.code)
        if not code:
            raise HTTPException(status_code=400, detail="Invalid code: use A-Z, 0-9, or '-'.")
        program.code = code
    if body.name is not None:
        program.name = _require_non_empty_name(body.name, field_name="name")
    if body.is_active is not None:
        program.is_active = bool(body.is_active)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Program code already exists.") from exc
    await db.refresh(program)
    return _program_payload(program)


@app.get("/admin/courses")
async def list_courses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    result = await db.execute(select(Course).order_by(Course.code.asc()))
    return [_course_payload(course) for course in result.scalars().all()]


@app.post("/admin/courses")
async def create_course(
    body: CourseCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    code = _normalize_catalog_code(body.code)
    if not code:
        raise HTTPException(status_code=400, detail="Invalid code: use A-Z, 0-9, or '-'.")
    display_code = _normalize_optional_catalog_code(body.display_code)
    name = _require_non_empty_name(body.name, field_name="name")

    course = Course(code=code, display_code=display_code, name=name, is_active=bool(body.is_active))
    db.add(course)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Course code already exists.") from exc
    await db.refresh(course)
    return _course_payload(course)


@app.patch("/admin/courses/{course_id}")
async def update_course(
    course_id: int,
    body: CourseUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    course = await _get_course_or_404(db, course_id)

    if body.code is None and body.display_code is None and body.name is None and body.is_active is None:
        raise HTTPException(status_code=400, detail="Provide at least one field to update.")

    if body.code is not None:
        code = _normalize_catalog_code(body.code)
        if not code:
            raise HTTPException(status_code=400, detail="Invalid code: use A-Z, 0-9, or '-'.")
        course.code = code
    if body.display_code is not None:
        course.display_code = _normalize_optional_catalog_code(body.display_code)
    if body.name is not None:
        course.name = _require_non_empty_name(body.name, field_name="name")
    if body.is_active is not None:
        course.is_active = bool(body.is_active)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Course code already exists.") from exc
    await db.refresh(course)
    return _course_payload(course)


@app.get("/admin/programs/{program_id}/courses")
async def list_program_courses(
    program_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    program = await _get_program_or_404(db, program_id)
    courses_result = await db.execute(
        select(Course)
        .join(ProgramCourse, ProgramCourse.course_id == Course.id)
        .where(ProgramCourse.program_id == program_id)
        .order_by(Course.code.asc())
    )
    courses = courses_result.scalars().all()
    return {
        "program": _program_payload(program),
        "courses": [_course_payload(course) for course in courses],
    }


@app.put("/admin/programs/{program_id}/courses/{course_id}")
async def map_course_to_program(
    program_id: int,
    course_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    await _get_program_or_404(db, program_id)
    await _get_course_or_404(db, course_id)

    existing = await db.execute(
        select(ProgramCourse).where(
            ProgramCourse.program_id == program_id,
            ProgramCourse.course_id == course_id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(ProgramCourse(program_id=program_id, course_id=course_id))
        await db.commit()
    return {"program_id": program_id, "course_id": course_id, "mapped": True}


@app.delete("/admin/programs/{program_id}/courses/{course_id}")
async def unmap_course_from_program(
    program_id: int,
    course_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    await _get_program_or_404(db, program_id)
    await _get_course_or_404(db, course_id)
    await db.execute(
        delete(ProgramCourse).where(
            ProgramCourse.program_id == program_id,
            ProgramCourse.course_id == course_id,
        )
    )
    await db.commit()
    return {"program_id": program_id, "course_id": course_id, "mapped": False}


@app.post("/admin/catalog/sync")
async def sync_catalog(
    body: CatalogSyncRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)

    snapshot_day: date
    if body.snapshot_date:
        try:
            snapshot_day = date.fromisoformat(body.snapshot_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="snapshot_date must be YYYY-MM-DD") from exc
    else:
        snapshot_day = date.today()

    try:
        result = await run_catalog_sync(
            db,
            snapshot_date=snapshot_day,
            dry_run=bool(body.dry_run),
            write_snapshot_files_to_disk=False,
        )
    except Exception as exc:
        await db.rollback()
        LOGGER.exception("Catalog sync failed")
        raise HTTPException(status_code=500, detail=f"Catalog sync failed: {exc}") from exc

    return result.to_dict()


@app.get("/admin/programs/{program_id}/plan")
async def get_program_plan(
    program_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    await _require_admin_user_or_403(user_id=user_id, db=db)
    program = await _get_program_or_404(db, program_id)

    result = await db.execute(
        select(ProgramCoursePlan)
        .where(ProgramCoursePlan.program_id == program_id)
        .order_by(ProgramCoursePlan.snapshot_date.desc(), ProgramCoursePlan.display_order.asc())
    )
    rows = result.scalars().all()
    return {
        "program": _program_payload(program),
        "rows": [_program_course_plan_payload(row) for row in rows],
    }


@app.post("/admin/register")
async def register_admin(
    body: AdminRegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    if not ADMIN_SECRET:
        raise HTTPException(status_code=503, detail="Admin registration is disabled on this server.")
    if body.secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret.")
    existing = await db.execute(select(AdminUser.id).where(AdminUser.user_id == user_id))
    if existing.scalar_one_or_none() is None:
        db.add(AdminUser(user_id=user_id))
        await db.commit()
    return {"status": "registered", "user_id": user_id}


@app.get("/admin/pending")
async def list_pending_lectures(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    if not await _is_admin(user_id, db):
        raise HTTPException(status_code=403, detail="Admin access required.")
    result = await db.execute(
        select(Lecture)
        .where(Lecture.is_approved == False, Lecture.is_deleted == False)
        .order_by(Lecture.created_at.desc())
    )
    lectures = result.scalars().all()
    display_overrides_by_code = await _course_display_overrides_by_code(
        db,
        [lecture.course_id for lecture in lectures],
    )
    return [
        _teachers_note_payload(
            lecture,
            is_saved=False,
            course_display=_resolve_course_display(lecture.course_id, display_overrides_by_code),
        )
        for lecture in lectures
    ]


@app.post("/lectures/{lecture_id}/approve")
async def approve_lecture(
    lecture_id: int,
    body: ApproveLectureRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    if not await _is_admin(user_id, db):
        raise HTTPException(status_code=403, detail="Admin access required.")
    lecture = await get_lecture_or_404(db, lecture_id)

    normalized_courseid, normalized_kind, normalized_lecture, normalized_year = _normalize_upload_naming_fields(
        body.courseid,
        body.kind,
        body.lecture,
        body.year,
        strict_kind=True,
    )
    active_course = await db.execute(
        select(Course.id).where(
            Course.code == normalized_courseid,
            Course.is_active == True,
        )
    )
    if active_course.scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail="Invalid courseid: must match an active catalog course.")

    lecture.course_id = normalized_courseid
    lecture.naming_kind = normalized_kind
    lecture.naming_lecture = normalized_lecture
    lecture.naming_year = normalized_year
    lecture.name = _build_standard_stem(normalized_courseid, normalized_kind, normalized_lecture, normalized_year)

    lecture.is_approved = True
    await db.commit()
    display_overrides_by_code = await _course_display_overrides_by_code(db, [lecture.course_id])
    return _teachers_note_payload(
        lecture,
        is_saved=False,
        course_display=_resolve_course_display(lecture.course_id, display_overrides_by_code),
    )


@app.post("/lectures/{lecture_id}/reject")
async def reject_lecture(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.uuid
    if not await _is_admin(user_id, db):
        raise HTTPException(status_code=403, detail="Admin access required.")
    lecture = await get_lecture_or_404(db, lecture_id)
    await _assert_lecture_can_be_permanently_deleted(int(lecture.id))
    deleted_id = int(lecture.id)
    await _permanently_delete_lecture(db, lecture)
    return {"id": deleted_id, "rejected": True}


@app.post("/lectures/{lecture_id}/regenerate-notes/jobs", status_code=status.HTTP_202_ACCEPTED)
async def start_regenerate_notes_job(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _cleanup_expired_jobs()

    lecture = await get_lecture_or_404(db, lecture_id)
    admin = await _is_admin(current_user.uuid, db)
    await assert_user_can_view_lecture(db, user_id=current_user.uuid, lecture=lecture, is_admin=admin)

    active_job = await _get_active_job_for_lecture(lecture_id)
    if active_job:
        return _job_public_state(active_job)

    context = await _load_regeneration_context(db, lecture_id)
    targets = _build_regeneration_targets(context["align_rows"], context["enriched_by_slide"])
    job = await _create_job(lecture_id=lecture_id, total_slides=len(targets))
    asyncio.create_task(_run_regenerate_notes_job(job["job_id"], lecture_id))
    return _job_public_state(job)


@app.get("/lectures/regenerate-notes/jobs/{job_id}")
async def get_regenerate_notes_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _cleanup_expired_jobs()
    job = await _get_job_snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    admin = await _is_admin(current_user.uuid, db)
    await _assert_user_can_view_regen_job(db, user_id=current_user.uuid, job=job, is_admin=admin)
    return _job_public_state(job)


@app.get("/lectures/regenerate-notes/jobs/{job_id}/events")
async def stream_regenerate_notes_job(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_query),
):
    await _cleanup_expired_jobs()
    job = await _get_job_snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    admin = await _is_admin(current_user.uuid, db)
    await _assert_user_can_view_regen_job(db, user_id=current_user.uuid, job=job, is_admin=admin)

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


@app.post("/lectures/{lecture_id}/regenerate-notes")
async def regenerate_notes(
    lecture_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lecture = await get_lecture_or_404(db, lecture_id)
    admin = await _is_admin(current_user.uuid, db)
    await assert_user_can_view_lecture(db, user_id=current_user.uuid, lecture=lecture, is_admin=admin)

    context = await _load_regeneration_context(db, lecture_id)
    course_context = await _lookup_course_context(db, context["course_id"])
    targets = _build_regeneration_targets(context["align_rows"], context["enriched_by_slide"])

    regenerated_slides = 0
    for batch in _chunk_items(targets, ENRICH_BATCH_SIZE):
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


class LectureChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class LectureChatRequest(BaseModel):
    message: str
    selected_text: str | None = None
    history: list[LectureChatMessage] = []


@app.post("/lectures/{lecture_id}/chat")
async def lecture_chat(
    lecture_id: int,
    body: LectureChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lecture = await get_lecture_or_404(db, lecture_id)
    admin = await _is_admin(current_user.uuid, db)
    await assert_user_can_view_lecture(db, user_id=current_user.uuid, lecture=lecture, is_admin=admin)

    data = await lecture_to_response(db, lecture_id)
    lecture_context = _chatbot.build_lecture_context(
        data["slides"],
        transcript=data.get("transcript"),
        alignment=data.get("alignment"),
    )
    history = [{"role": m.role, "content": m.content} for m in body.history]

    try:
        reply = await run_in_threadpool(
            _chatbot.chat,
            lecture_context,
            history,
            body.message,
            body.selected_text,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"reply": reply}
