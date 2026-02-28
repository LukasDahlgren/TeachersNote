import logging
import os

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "lecturesummary")

_missing = [k for k, v, d in [("DB_HOST", DB_HOST, "localhost"), ("DB_USER", DB_USER, "root"), ("DB_PASSWORD", DB_PASSWORD, ""), ("DB_NAME", DB_NAME, "lecturesummary")] if v == d]
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
    lecture_columns = {column["name"] for column in inspector.get_columns("lectures")}
    if "is_archived" not in lecture_columns:
        sync_conn.execute(
            text("ALTER TABLE lectures ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0")
        )


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
