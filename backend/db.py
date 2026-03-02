import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect, text
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
        sync_conn.execute(
            text("ALTER TABLE lectures ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0")
        )
    if "uploaded_by" not in lecture_columns:
        sync_conn.execute(
            text("ALTER TABLE lectures ADD COLUMN uploaded_by VARCHAR(255) NULL")
        )
    if "is_approved" not in lecture_columns:
        # All existing lectures are approved so they remain visible
        sync_conn.execute(
            text("ALTER TABLE lectures ADD COLUMN is_approved BOOLEAN NOT NULL DEFAULT 1")
        )
    if "course_id" not in lecture_columns:
        sync_conn.execute(
            text("ALTER TABLE lectures ADD COLUMN course_id VARCHAR(64) NULL")
        )
        sync_conn.execute(
            text("CREATE INDEX ix_lectures_course_id ON lectures (course_id)")
        )

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
        sync_conn.execute(
            text("ALTER TABLE courses ADD COLUMN display_code VARCHAR(64) NULL")
        )
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
        sync_conn.execute(
            text(
                "CREATE INDEX ix_program_course_plan_program_term_display "
                "ON program_course_plan (program_id, term_label, display_order)"
            )
        )
    if "ix_program_course_plan_program_group_type" not in plan_indexes:
        sync_conn.execute(
            text(
                "CREATE INDEX ix_program_course_plan_program_group_type "
                "ON program_course_plan (program_id, group_type)"
            )
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


def _derive_course_id_from_lecture_name(name: str) -> str | None:
    stem = re.sub(r"\.[^./\\]+$", "", name.strip())
    if not stem:
        return None
    first_part = re.split(r"[-_\s]+", stem, maxsplit=1)[0]
    normalized = re.sub(r"[^A-Za-z0-9-]", "", first_part).upper().strip("-")
    return normalized or None


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
