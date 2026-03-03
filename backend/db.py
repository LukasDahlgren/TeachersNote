import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "teachersnote")

_missing = [k for k, v, d in [("DB_HOST", DB_HOST, "localhost"), ("DB_USER", DB_USER, "root"), ("DB_PASSWORD", DB_PASSWORD, ""), ("DB_NAME", DB_NAME, "teachersnote")] if v == d]
if _missing:
    logging.warning("DB config using default/empty values for: %s", ", ".join(_missing))

DATABASE_URL = (
    f"mysql+aiomysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    from models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schema_compatibility)


def _execute_ddl_ignore_duplicate(sync_conn, statement: str) -> None:
    try:
        sync_conn.execute(text(statement))
    except OperationalError as exc:
        orig = getattr(exc, "orig", None)
        code = None
        if orig is not None and getattr(orig, "args", None):
            try:
                code = int(orig.args[0])
            except (TypeError, ValueError):
                code = None
        message = str(orig or exc).lower()
        if code in {1060, 1061}:
            return
        if "duplicate column name" in message or "duplicate key name" in message:
            return
        raise


def _ensure_schema_compatibility(sync_conn) -> None:
    inspector = inspect(sync_conn)

    sync_conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY,
                uuid VARCHAR(36) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(255) NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX ix_users_uuid (uuid),
                INDEX ix_users_email (email)
            )
            """
        )
    )

    lecture_columns = {column["name"] for column in inspector.get_columns("lectures")}
    if "is_archived" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0")
    if "uploaded_by" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN uploaded_by VARCHAR(255) NULL")
    if "is_approved" not in lecture_columns:
        # All existing lectures are approved so they remain visible
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN is_approved BOOLEAN NOT NULL DEFAULT 1")
    if "course_id" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN course_id VARCHAR(64) NULL")
        _execute_ddl_ignore_duplicate(sync_conn, "CREATE INDEX ix_lectures_course_id ON lectures (course_id)")
    if "naming_kind" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN naming_kind VARCHAR(64) NULL")
    if "naming_lecture" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN naming_lecture VARCHAR(255) NULL")
    if "naming_year" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN naming_year VARCHAR(4) NULL")
    if "upload_courseid_raw" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN upload_courseid_raw VARCHAR(64) NULL")
    if "upload_kind_raw" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN upload_kind_raw VARCHAR(64) NULL")
    if "upload_lecture_raw" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN upload_lecture_raw VARCHAR(255) NULL")
    if "upload_year_raw" not in lecture_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE lectures ADD COLUMN upload_year_raw VARCHAR(4) NULL")

    sync_conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS programs (
                id INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY,
                code VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
        )
    )
    sync_conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY,
                code VARCHAR(64) NOT NULL UNIQUE,
                display_code VARCHAR(64) NULL,
                name VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
        )
    )
    course_columns = {column["name"] for column in inspector.get_columns("courses")}
    if "display_code" not in course_columns:
        _execute_ddl_ignore_duplicate(sync_conn, "ALTER TABLE courses ADD COLUMN display_code VARCHAR(64) NULL")
    sync_conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS program_courses (
                program_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (program_id, course_id),
                CONSTRAINT fk_program_courses_program
                    FOREIGN KEY (program_id) REFERENCES programs(id) ON DELETE CASCADE,
                CONSTRAINT fk_program_courses_course
                    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
            )
            """
        )
    )
    sync_conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS student_profiles (
                user_id VARCHAR(255) NOT NULL PRIMARY KEY,
                program_id INTEGER NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_student_profiles_program
                    FOREIGN KEY (program_id) REFERENCES programs(id) ON DELETE SET NULL
            )
            """
        )
    )
    sync_conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS student_courses (
                user_id VARCHAR(255) NOT NULL,
                course_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, course_id),
                CONSTRAINT fk_student_courses_profile
                    FOREIGN KEY (user_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE,
                CONSTRAINT fk_student_courses_course
                    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
            )
            """
        )
    )

    sync_conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS program_course_plan (
                id INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY,
                program_id INTEGER NOT NULL,
                course_id INTEGER NULL,
                term_label VARCHAR(128) NOT NULL,
                group_type VARCHAR(16) NOT NULL,
                group_label VARCHAR(255) NULL,
                course_code VARCHAR(64) NULL,
                course_name_sv VARCHAR(255) NOT NULL,
                course_url TEXT NOT NULL,
                display_order INTEGER NOT NULL,
                snapshot_date DATE NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_program_course_plan_program
                    FOREIGN KEY (program_id) REFERENCES programs(id) ON DELETE CASCADE,
                CONSTRAINT fk_program_course_plan_course
                    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE SET NULL,
                CONSTRAINT uq_program_course_plan_position
                    UNIQUE (program_id, snapshot_date, display_order)
            )
            """
        )
    )
    plan_indexes = {
        index_info["name"]
        for index_info in inspector.get_indexes("program_course_plan")
        if index_info.get("name")
    }
    if "ix_program_course_plan_program_term_display" not in plan_indexes:
        _execute_ddl_ignore_duplicate(
            sync_conn,
            "CREATE INDEX ix_program_course_plan_program_term_display "
            "ON program_course_plan (program_id, term_label, display_order)",
        )
    if "ix_program_course_plan_program_group_type" not in plan_indexes:
        _execute_ddl_ignore_duplicate(
            sync_conn,
            "CREATE INDEX ix_program_course_plan_program_group_type "
            "ON program_course_plan (program_id, group_type)",
        )

    rows = sync_conn.execute(
        text("SELECT id, name FROM lectures WHERE course_id IS NULL OR course_id = ''")
    ).fetchall()
    for row in rows:
        lecture_id = int(row[0])
        name = str(row[1] or "")
        derived = _derive_course_id_from_lecture_name(name)
        if not derived:
            continue
        sync_conn.execute(
            text("UPDATE lectures SET course_id = :course_id WHERE id = :lecture_id"),
            {"course_id": derived, "lecture_id": lecture_id},
        )

    upload_rows = sync_conn.execute(
        text(
            """
            SELECT
                id,
                name,
                course_id,
                naming_kind,
                naming_lecture,
                naming_year,
                upload_courseid_raw,
                upload_kind_raw,
                upload_lecture_raw,
                upload_year_raw
            FROM lectures
            """
        )
    ).fetchall()
    for row in upload_rows:
        lecture_id = int(row[0])
        lecture_name = str(row[1] or "")
        canonical_courseid = _clean_optional_text(row[2])
        canonical_kind = _clean_optional_text(row[3])
        canonical_lecture = _clean_optional_text(row[4])
        canonical_year = _clean_optional_text(row[5])
        raw_courseid = _clean_optional_text(row[6])
        raw_kind = _clean_optional_text(row[7])
        raw_lecture = _clean_optional_text(row[8])
        raw_year = _clean_optional_text(row[9])

        next_raw_courseid, next_raw_kind, next_raw_lecture, next_raw_year = _resolve_backfilled_upload_raw_fields(
            lecture_name=lecture_name,
            canonical_courseid=canonical_courseid,
            canonical_kind=canonical_kind,
            canonical_lecture=canonical_lecture,
            canonical_year=canonical_year,
            existing_raw_courseid=raw_courseid,
            existing_raw_kind=raw_kind,
            existing_raw_lecture=raw_lecture,
            existing_raw_year=raw_year,
        )

        if (
            next_raw_courseid == raw_courseid
            and next_raw_kind == raw_kind
            and next_raw_lecture == raw_lecture
            and next_raw_year == raw_year
        ):
            continue

        sync_conn.execute(
            text(
                """
                UPDATE lectures
                SET
                    upload_courseid_raw = :upload_courseid_raw,
                    upload_kind_raw = :upload_kind_raw,
                    upload_lecture_raw = :upload_lecture_raw,
                    upload_year_raw = :upload_year_raw
                WHERE id = :lecture_id
                """
            ),
            {
                "upload_courseid_raw": next_raw_courseid,
                "upload_kind_raw": next_raw_kind,
                "upload_lecture_raw": next_raw_lecture,
                "upload_year_raw": next_raw_year,
                "lecture_id": lecture_id,
            },
        )


def _derive_course_id_from_lecture_name(name: str) -> str | None:
    stem = re.sub(r"\.[^./\\]+$", "", name.strip())
    if not stem:
        return None
    first_part = re.split(r"[-_\s]+", stem, maxsplit=1)[0]
    normalized = re.sub(r"[^A-Za-z0-9-]", "", first_part).upper().strip("-")
    return normalized or None


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


def _normalize_kind(raw: str) -> str:
    value = str(raw or "").strip().lower()
    value = re.sub(r"[ _]+", "-", value)
    value = re.sub(r"[^a-z0-9-]", "", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def _normalize_lecture(raw: str) -> str:
    return _normalize_naming_token(
        raw,
        uppercase=False,
        invalid_chars_pattern=r"[^A-Za-z0-9-]",
    )


def _clean_optional_text(value: object | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _derive_upload_naming_from_lecture_name(name: str) -> tuple[str | None, str | None, str | None, str | None]:
    stem = re.sub(r"\.[^./\\]+$", "", str(name or "").strip())
    if not stem:
        return None, None, None, None

    parts = stem.split("-")
    if len(parts) < 4:
        return None, None, None, None

    maybe_year = parts[-1]
    maybe_suffix = parts[-1] if len(parts) >= 5 else None
    has_numeric_suffix = maybe_suffix is not None and maybe_suffix.isdigit()
    if maybe_year.isdigit() and len(maybe_year) == 4:
        body_parts = parts[:-1]
    elif has_numeric_suffix and parts[-2].isdigit() and len(parts[-2]) == 4:
        maybe_year = parts[-2]
        body_parts = parts[:-2]
    else:
        return None, None, None, None

    if len(body_parts) < 3:
        return None, None, None, None

    courseid = _normalize_courseid(body_parts[0]) or None
    raw_kind = _normalize_kind(body_parts[1]) or None
    lecture = _normalize_lecture("-".join(body_parts[2:])) or None
    year = maybe_year if re.fullmatch(r"\d{4}", maybe_year) else None
    return courseid, raw_kind, lecture, year


def _resolve_backfilled_upload_raw_fields(
    *,
    lecture_name: str,
    canonical_courseid: str | None,
    canonical_kind: str | None,
    canonical_lecture: str | None,
    canonical_year: str | None,
    existing_raw_courseid: str | None,
    existing_raw_kind: str | None,
    existing_raw_lecture: str | None,
    existing_raw_year: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    parsed_courseid, parsed_kind, parsed_lecture, parsed_year = _derive_upload_naming_from_lecture_name(lecture_name)
    return (
        existing_raw_courseid or canonical_courseid or parsed_courseid,
        existing_raw_kind or canonical_kind or parsed_kind,
        existing_raw_lecture or canonical_lecture or parsed_lecture,
        existing_raw_year or canonical_year or parsed_year,
    )


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
