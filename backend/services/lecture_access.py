from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, NamedTuple

from fastapi import HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from models import AdminUser, Lecture, LectureAccess, LectureSave
except ImportError:  # pragma: no cover - package import fallback
    from backend.models import AdminUser, Lecture, LectureAccess, LectureSave  # type: ignore[no-redef]

try:
    from services.serializers import _archive_response_payload
except ImportError:  # pragma: no cover - package import fallback
    from backend.services.serializers import _archive_response_payload  # type: ignore[no-redef]


BACKEND_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BACKEND_DIR / "uploads"
GENERATED_DIR = BACKEND_DIR / "generated"
SOURCE_PDFS_DIR = BACKEND_DIR / "source_pdfs"
ARCHIVED_GENERATED_DIR = GENERATED_DIR / "archived"
LOGGER = logging.getLogger(__name__)


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


class StagedLectureAsset(NamedTuple):
    original_path: Path
    staged_path: Path


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


async def _assert_lecture_can_be_permanently_deleted(
    lecture_id: int,
    *,
    get_active_job_for_lecture: Callable[[int], Awaitable[dict[str, Any] | None]],
    get_active_upload_job_for_lecture: Callable[[int], Awaitable[dict[str, Any] | None]],
) -> None:
    active_regen_job = await get_active_job_for_lecture(lecture_id)
    if active_regen_job is not None:
        raise HTTPException(
            status_code=409,
            detail="Lecture is currently regenerating notes. Wait for the job to finish before deleting it.",
        )

    active_upload_job = await get_active_upload_job_for_lecture(lecture_id)
    if active_upload_job is not None:
        raise HTTPException(
            status_code=409,
            detail="Lecture is still processing. Wait for the upload job to finish before deleting it.",
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


def _lecture_has_visible_pptx(lecture: Lecture) -> bool:
    if not lecture.pptx_path:
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


__all__ = [
    "StagedLectureAsset",
    "_apply_archive_state",
    "_assert_lecture_can_be_permanently_deleted",
    "_build_collision_safe_destination",
    "_find_lecture_for_asset_path",
    "_find_reusable_lecture_by_pdf_hash",
    "_grant_reused_lecture_access",
    "_is_admin",
    "_lecture_asset_paths_for_permanent_delete",
    "_lecture_has_visible_pptx",
    "_non_admin_lecture_access_filter",
    "_path_is_archived_generated",
    "_path_is_within",
    "_permanently_delete_lecture",
    "_plan_asset_move",
    "_require_admin_user_or_403",
    "_resolve_generated_download_path",
    "_resolve_lecture_asset_path",
    "_resolve_pdf_download_path",
    "_rollback_staged_lecture_assets",
    "_saved_lecture_ids_for_user",
    "_stored_path_variants",
    "_to_backend_relative_path",
    "_user_has_explicit_lecture_access",
    "assert_user_can_view_lecture",
    "can_view_lecture",
    "get_lecture_or_404",
    "grant_lecture_access_for_user",
    "save_lecture_for_user",
    "unsave_lecture_for_user",
]

