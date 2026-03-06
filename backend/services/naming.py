from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import NamedTuple

from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parent.parent
GENERATED_DIR = BACKEND_DIR / "generated"
SOURCE_PDFS_DIR = BACKEND_DIR / "source_pdfs"
ALLOWED_CANONICAL_KINDS = {"lecture", "other"}


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


def _canonical_course_code(raw_course_id: str | None) -> str:
    value = (raw_course_id or "").strip()
    if not value:
        return ""
    return _normalize_catalog_code(value)


__all__ = [
    "ALLOWED_CANONICAL_KINDS",
    "UploadNamingResolution",
    "UploadRawNaming",
    "UploadSubmissionResolution",
    "_build_standard_stem",
    "_build_unique_generated_paths",
    "_canonical_course_code",
    "_derive_temporary_lecture_name",
    "_join_text",
    "_normalize_catalog_code",
    "_normalize_courseid",
    "_normalize_kind",
    "_normalize_lecture",
    "_normalize_optional_catalog_code",
    "_normalize_upload_naming_fields",
    "_parse_standard_upload_name",
    "_raw_upload_naming_fields",
    "_require_non_empty_name",
    "_resolve_upload_naming",
    "_resolve_upload_submission_naming",
    "_temporary_lecture_token_from_slides",
    "_temporary_upload_stem_from_filename",
    "_validate_year",
]
