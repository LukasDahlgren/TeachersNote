from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

import importlib.util
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_PATH = REPO_ROOT / "scripts" / "collect_idsv_catalog.py"
_COLLECTOR_SPEC = importlib.util.spec_from_file_location("teachersnote_collect_idsv_catalog", COLLECTOR_PATH)
if _COLLECTOR_SPEC is None or _COLLECTOR_SPEC.loader is None:
    raise RuntimeError(f"Unable to load collector module from {COLLECTOR_PATH}")
_COLLECTOR_MODULE = importlib.util.module_from_spec(_COLLECTOR_SPEC)
sys.modules.setdefault(_COLLECTOR_SPEC.name, _COLLECTOR_MODULE)
_COLLECTOR_SPEC.loader.exec_module(_COLLECTOR_MODULE)

DSV_INSTITUTION_NAME = _COLLECTOR_MODULE.DSV_INSTITUTION_NAME
SourceProgram = _COLLECTOR_MODULE.CatalogProgram
SourceProgramCourseEntry = _COLLECTOR_MODULE.ProgramCourseEntry
SourceStandaloneCourse = _COLLECTOR_MODULE.StandaloneCourse
collect_catalog_snapshot = _COLLECTOR_MODULE.collect_catalog_snapshot
write_snapshot_files = _COLLECTOR_MODULE.write_snapshot_files

_ALLOWED_GROUP_TYPES = {"mandatory", "optional"}


@dataclass(frozen=True)
class StandaloneCourse:
    snapshot_date: str
    course_code: str
    course_name_sv: str
    level: str
    catalog_url: str
    institution_name: str


@dataclass(frozen=True)
class ProgramInfo:
    snapshot_date: str
    program_code: str
    program_name_sv: str
    level: str
    catalog_url: str
    institution_name: str


@dataclass(frozen=True)
class ProgramCourseEntry:
    snapshot_date: str
    program_code: str
    program_name_sv: str
    term_label: str
    group_type: str
    group_label: str
    course_code: str | None
    course_name_sv: str
    course_url: str


@dataclass(frozen=True)
class CatalogSyncResult:
    snapshot_date: str
    standalone_count: int
    program_count: int
    program_course_count: int
    program_plan_rows_written: int
    programs_created: int
    programs_updated: int
    programs_deactivated: int
    courses_created: int
    courses_updated: int
    courses_deactivated: int
    mappings_added: int
    mappings_removed: int
    warnings: list[str]
    duration_seconds: float
    dry_run: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_date": self.snapshot_date,
            "standalone_count": self.standalone_count,
            "program_count": self.program_count,
            "program_course_count": self.program_course_count,
            "program_plan_rows_written": self.program_plan_rows_written,
            "programs_created": self.programs_created,
            "programs_updated": self.programs_updated,
            "programs_deactivated": self.programs_deactivated,
            "courses_created": self.courses_created,
            "courses_updated": self.courses_updated,
            "courses_deactivated": self.courses_deactivated,
            "mappings_added": self.mappings_added,
            "mappings_removed": self.mappings_removed,
            "warnings": list(self.warnings),
            "duration_seconds": self.duration_seconds,
            "dry_run": self.dry_run,
        }


@dataclass(frozen=True)
class CatalogChangePlan:
    programs_created_codes: set[str]
    programs_updated_codes: set[str]
    programs_deactivated_codes: set[str]
    courses_created_codes: set[str]
    courses_updated_codes: set[str]
    courses_deactivated_codes: set[str]


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def normalize_catalog_code(raw: str | None) -> str:
    value = _clean_text(raw)
    value = value.upper()
    value = re.sub(r"[ _]+", "-", value)
    value = re.sub(r"[^A-Z0-9-]", "", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def normalize_group_type(raw: str | None) -> str:
    value = _clean_text(raw).lower()
    if value in _ALLOWED_GROUP_TYPES:
        return value
    return "mandatory"


def _is_dsv_institution(name: str) -> bool:
    return DSV_INSTITUTION_NAME.lower() in _clean_text(name).lower()


def normalize_standalone_courses(
    rows: Iterable[SourceStandaloneCourse],
    warnings: list[str],
) -> list[StandaloneCourse]:
    normalized: list[StandaloneCourse] = []
    seen_codes: set[str] = set()

    for row in rows:
        code = normalize_catalog_code(row.course_code)
        name = _clean_text(row.course_name_sv)
        level = _clean_text(row.level)
        url = _clean_text(row.catalog_url)
        institution = _clean_text(row.institution_name)

        if not code or not name or not url:
            warnings.append(
                "standalone: skipped row with missing required value "
                f"(code='{code}', name='{name}', url='{url}')"
            )
            continue
        if code in seen_codes:
            continue
        if not _is_dsv_institution(institution):
            warnings.append(
                f"{code}: institution check failed (expected DSV, got '{institution}')"
            )
            continue

        normalized.append(
            StandaloneCourse(
                snapshot_date=row.snapshot_date,
                course_code=code,
                course_name_sv=name,
                level=level,
                catalog_url=url,
                institution_name=institution,
            )
        )
        seen_codes.add(code)

    normalized.sort(key=lambda item: (item.course_code, item.course_name_sv))
    return normalized


def normalize_programs(rows: Iterable[SourceProgram], warnings: list[str]) -> list[ProgramInfo]:
    normalized: list[ProgramInfo] = []
    seen_codes: set[str] = set()

    for row in rows:
        code = normalize_catalog_code(row.program_code)
        name = _clean_text(row.program_name_sv)
        level = _clean_text(row.level)
        url = _clean_text(row.catalog_url)
        institution = _clean_text(row.institution_name) or DSV_INSTITUTION_NAME

        if not code or not name or not url:
            warnings.append(
                "program: skipped row with missing required value "
                f"(code='{code}', name='{name}', url='{url}')"
            )
            continue
        if code in seen_codes:
            continue

        normalized.append(
            ProgramInfo(
                snapshot_date=row.snapshot_date,
                program_code=code,
                program_name_sv=name,
                level=level,
                catalog_url=url,
                institution_name=institution,
            )
        )
        seen_codes.add(code)

    normalized.sort(key=lambda item: item.program_code)
    return normalized


def normalize_program_course_entries(
    rows: Iterable[SourceProgramCourseEntry],
    warnings: list[str],
) -> list[ProgramCourseEntry]:
    normalized: list[ProgramCourseEntry] = []

    for row in rows:
        program_code = normalize_catalog_code(row.program_code)
        program_name = _clean_text(row.program_name_sv)
        term_label = _clean_text(row.term_label)
        group_type = normalize_group_type(row.group_type)
        group_label = _clean_text(row.group_label)
        course_code = normalize_catalog_code(row.course_code or "") or None
        course_name = _clean_text(row.course_name_sv)
        course_url = _clean_text(row.course_url)

        if not program_code or not program_name or not course_name or not course_url:
            warnings.append(
                "program-course: skipped row with missing required value "
                f"(program_code='{program_code}', course_name='{course_name}', course_url='{course_url}')"
            )
            continue
        if not term_label:
            warnings.append(f"{program_code}: missing term_label for '{course_code or course_name}'")
        if course_code is None:
            warnings.append(f"{program_code}: missing course_code for '{course_name}' ({course_url})")

        normalized.append(
            ProgramCourseEntry(
                snapshot_date=row.snapshot_date,
                program_code=program_code,
                program_name_sv=program_name,
                term_label=term_label,
                group_type=group_type,
                group_label=group_label,
                course_code=course_code,
                course_name_sv=course_name,
                course_url=course_url,
            )
        )

    return normalized


def build_course_catalog(
    standalone_rows: Iterable[StandaloneCourse],
    program_rows: Iterable[ProgramCourseEntry],
) -> dict[str, str]:
    catalog: dict[str, str] = {}
    for row in standalone_rows:
        catalog[row.course_code] = row.course_name_sv
    for row in program_rows:
        if row.course_code and row.course_code not in catalog:
            catalog[row.course_code] = row.course_name_sv
    return catalog


def compute_catalog_change_plan(
    existing_programs: dict[str, Any],
    incoming_programs: dict[str, ProgramInfo],
    existing_courses: dict[str, Any],
    incoming_courses: dict[str, str],
) -> CatalogChangePlan:
    program_created = {code for code in incoming_programs if code not in existing_programs}
    program_updated = {
        code
        for code, incoming in incoming_programs.items()
        if code in existing_programs
        and (
            _clean_text(existing_programs[code].name) != incoming.program_name_sv
            or not bool(existing_programs[code].is_active)
        )
    }
    program_deactivated = {
        code
        for code, existing in existing_programs.items()
        if code not in incoming_programs and bool(existing.is_active)
    }

    course_created = {code for code in incoming_courses if code not in existing_courses}
    course_updated = {
        code
        for code, name in incoming_courses.items()
        if code in existing_courses
        and (
            _clean_text(existing_courses[code].name) != name
            or not bool(existing_courses[code].is_active)
        )
    }
    course_deactivated = {
        code
        for code, existing in existing_courses.items()
        if code not in incoming_courses and bool(existing.is_active)
    }

    return CatalogChangePlan(
        programs_created_codes=program_created,
        programs_updated_codes=program_updated,
        programs_deactivated_codes=program_deactivated,
        courses_created_codes=course_created,
        courses_updated_codes=course_updated,
        courses_deactivated_codes=course_deactivated,
    )


def compute_mapping_deltas(
    existing_mappings: set[tuple[str, str]],
    target_mappings: set[tuple[str, str]],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    to_add = target_mappings - existing_mappings
    to_remove = existing_mappings - target_mappings
    return to_add, to_remove


def build_program_plan_payloads(
    program_rows: Iterable[ProgramCourseEntry],
    *,
    program_id_by_code: dict[str, int],
    course_id_by_code: dict[str, int],
    snapshot_day: date,
) -> list[dict[str, Any]]:
    display_order_by_program: dict[str, int] = {}
    payloads: list[dict[str, Any]] = []

    for row in program_rows:
        if row.program_code not in program_id_by_code:
            continue
        display_order = display_order_by_program.get(row.program_code, 0) + 1
        display_order_by_program[row.program_code] = display_order

        payloads.append(
            {
                "program_id": program_id_by_code[row.program_code],
                "course_id": course_id_by_code.get(row.course_code or ""),
                "term_label": row.term_label,
                "group_type": normalize_group_type(row.group_type),
                "group_label": row.group_label,
                "course_code": row.course_code,
                "course_name_sv": row.course_name_sv,
                "course_url": row.course_url,
                "display_order": display_order,
                "snapshot_date": snapshot_day,
            }
        )

    return payloads


def apply_code_updates(
    existing_state: dict[str, dict[str, Any]],
    incoming: dict[str, str],
    *,
    dry_run: bool,
) -> dict[str, dict[str, Any]]:
    if dry_run:
        return {code: value.copy() for code, value in existing_state.items()}

    next_state = {code: value.copy() for code, value in existing_state.items()}
    for code, name in incoming.items():
        current = next_state.get(code)
        if current is None:
            next_state[code] = {"name": name, "is_active": True}
        else:
            current["name"] = name
            current["is_active"] = True

    for code, current in next_state.items():
        if code not in incoming:
            current["is_active"] = False

    return next_state


def _collect_snapshot_sync(snapshot_date: str, write_files: bool) -> tuple[
    list[StandaloneCourse],
    list[ProgramInfo],
    list[ProgramCourseEntry],
    list[str],
]:
    snapshot = collect_catalog_snapshot(snapshot_date)
    warnings = list(snapshot.warnings)

    standalone_rows = normalize_standalone_courses(snapshot.standalone_courses, warnings)
    program_rows = normalize_programs(snapshot.programs, warnings)
    program_course_rows = normalize_program_course_entries(snapshot.program_courses, warnings)

    if write_files:
        out_dir = Path(os.getenv("CATALOG_SYNC_OUT_DIR", Path(__file__).resolve().parent.parent / "out"))
        write_snapshot_files(snapshot, out_dir)

    return standalone_rows, program_rows, program_course_rows, warnings


async def run_catalog_sync(
    db: "AsyncSession",
    *,
    snapshot_date: date | None = None,
    dry_run: bool = False,
    write_snapshot_files_to_disk: bool = False,
) -> CatalogSyncResult:
    from sqlalchemy import delete, select

    from models import Course, Program, ProgramCourse, ProgramCoursePlan

    started = time.monotonic()
    snapshot_day = snapshot_date or date.today()
    snapshot_date_text = snapshot_day.isoformat()

    standalone_rows, program_rows, program_course_rows, warnings = await asyncio.to_thread(
        _collect_snapshot_sync,
        snapshot_date_text,
        write_snapshot_files_to_disk,
    )

    incoming_programs = {row.program_code: row for row in program_rows}
    incoming_courses = build_course_catalog(standalone_rows, program_course_rows)

    existing_program_list = (await db.execute(select(Program))).scalars().all()
    existing_course_list = (await db.execute(select(Course))).scalars().all()
    existing_programs = {normalize_catalog_code(program.code): program for program in existing_program_list}
    existing_courses = {normalize_catalog_code(course.code): course for course in existing_course_list}

    change_plan = compute_catalog_change_plan(
        existing_programs=existing_programs,
        incoming_programs=incoming_programs,
        existing_courses=existing_courses,
        incoming_courses=incoming_courses,
    )

    scope_program_codes = sorted(incoming_programs.keys())
    existing_mapping_pairs: set[tuple[str, str]] = set()
    if scope_program_codes:
        mapping_result = await db.execute(
            select(Program.code, Course.code)
            .select_from(ProgramCourse)
            .join(Program, Program.id == ProgramCourse.program_id)
            .join(Course, Course.id == ProgramCourse.course_id)
            .where(Program.code.in_(scope_program_codes))
        )
        existing_mapping_pairs = {
            (normalize_catalog_code(program_code), normalize_catalog_code(course_code))
            for program_code, course_code in mapping_result
        }

    target_mapping_pairs = {
        (row.program_code, row.course_code)
        for row in program_course_rows
        if row.course_code and row.program_code in incoming_programs
    }
    mappings_to_add, mappings_to_remove = compute_mapping_deltas(
        existing_mapping_pairs,
        target_mapping_pairs,
    )

    if not dry_run:
        for code in change_plan.programs_created_codes:
            incoming = incoming_programs[code]
            db.add(Program(code=code, name=incoming.program_name_sv, is_active=True))

        for code in change_plan.programs_updated_codes:
            incoming = incoming_programs[code]
            existing = existing_programs[code]
            existing.name = incoming.program_name_sv
            existing.is_active = True

        for code in change_plan.programs_deactivated_codes:
            existing_programs[code].is_active = False

        for code in change_plan.courses_created_codes:
            db.add(Course(code=code, name=incoming_courses[code], is_active=True))

        for code in change_plan.courses_updated_codes:
            existing = existing_courses[code]
            existing.name = incoming_courses[code]
            existing.is_active = True

        for code in change_plan.courses_deactivated_codes:
            existing_courses[code].is_active = False

        await db.flush()

        program_objects = (
            await db.execute(select(Program).where(Program.code.in_(scope_program_codes)))
        ).scalars().all()
        program_id_by_code = {normalize_catalog_code(program.code): int(program.id) for program in program_objects}

        mapping_course_codes = sorted({
            course_code
            for _, course_code in (existing_mapping_pairs | target_mapping_pairs)
            if course_code
        })
        course_id_by_code: dict[str, int] = {}
        if mapping_course_codes:
            course_objects = (
                await db.execute(select(Course).where(Course.code.in_(mapping_course_codes)))
            ).scalars().all()
            course_id_by_code = {normalize_catalog_code(course.code): int(course.id) for course in course_objects}

        # Remove stale mappings and add missing mappings for programs in snapshot scope.
        for program_code, course_code in mappings_to_remove:
            program_id = program_id_by_code.get(program_code)
            course_id = course_id_by_code.get(course_code)
            if program_id is None or course_id is None:
                continue
            await db.execute(
                delete(ProgramCourse).where(
                    ProgramCourse.program_id == program_id,
                    ProgramCourse.course_id == course_id,
                )
            )

        for program_code, course_code in mappings_to_add:
            program_id = program_id_by_code.get(program_code)
            course_id = course_id_by_code.get(course_code)
            if program_id is None or course_id is None:
                continue
            db.add(ProgramCourse(program_id=program_id, course_id=course_id))

        scope_program_ids = list(program_id_by_code.values())
        if scope_program_ids:
            await db.execute(
                delete(ProgramCoursePlan).where(ProgramCoursePlan.program_id.in_(scope_program_ids))
            )

        program_plan_payloads = build_program_plan_payloads(
            program_course_rows,
            program_id_by_code=program_id_by_code,
            course_id_by_code=course_id_by_code,
            snapshot_day=snapshot_day,
        )
        for payload in program_plan_payloads:
            db.add(ProgramCoursePlan(**payload))

        await db.commit()
        program_plan_rows_written = len(program_plan_payloads)
    else:
        program_plan_rows_written = len(
            build_program_plan_payloads(
                program_course_rows,
                program_id_by_code={code: index + 1 for index, code in enumerate(scope_program_codes)},
                course_id_by_code={code: index + 1 for index, code in enumerate(sorted(incoming_courses.keys()))},
                snapshot_day=snapshot_day,
            )
        )

    duration_seconds = round(time.monotonic() - started, 3)

    return CatalogSyncResult(
        snapshot_date=snapshot_date_text,
        standalone_count=len(standalone_rows),
        program_count=len(program_rows),
        program_course_count=len(program_course_rows),
        program_plan_rows_written=program_plan_rows_written,
        programs_created=len(change_plan.programs_created_codes),
        programs_updated=len(change_plan.programs_updated_codes),
        programs_deactivated=len(change_plan.programs_deactivated_codes),
        courses_created=len(change_plan.courses_created_codes),
        courses_updated=len(change_plan.courses_updated_codes),
        courses_deactivated=len(change_plan.courses_deactivated_codes),
        mappings_added=len(mappings_to_add),
        mappings_removed=len(mappings_to_remove),
        warnings=warnings,
        duration_seconds=duration_seconds,
        dry_run=dry_run,
    )
