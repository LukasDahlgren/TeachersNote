"""
Backfill existing enriched notes into canonical formatting and optionally sync PPTX files.

Usage (from backend/):
  python backfill_enriched_notes.py            # dry-run
  python backfill_enriched_notes.py --apply    # write DB updates + regenerate PPTX
"""

import argparse
import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select

from db import AsyncSessionLocal, init_db
from models import EnrichedSlide, Lecture
from pipeline import generate_presentation_from_enhanced
from scripts.enrich import normalize_enriched_payload

BACKEND_DIR = Path(__file__).parent.resolve()


def _resolve_lecture_asset_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (BACKEND_DIR / candidate).resolve()


def _normalized_payload_from_row(row: EnrichedSlide) -> dict[str, Any]:
    return normalize_enriched_payload({
        "summary": row.summary,
        "slide_content": row.slide_content,
        "lecturer_additions": row.lecturer_additions,
        "key_takeaways": row.key_takeaways,
    })


def _row_needs_update(row: EnrichedSlide, normalized: dict[str, Any]) -> bool:
    current_takeaways = row.key_takeaways if isinstance(row.key_takeaways, list) else []
    return (
        row.summary != normalized["summary"]
        or row.slide_content != normalized["slide_content"]
        or row.lecturer_additions != normalized["lecturer_additions"]
        or current_takeaways != normalized["key_takeaways"]
    )


def _pptx_sync_paths(lecture: Lecture) -> tuple[Path | None, Path | None, str | None]:
    if not lecture.pdf_path:
        return None, None, "missing lecture.pdf_path"
    if not lecture.pptx_path:
        return None, None, "missing lecture.pptx_path"

    pdf_path = _resolve_lecture_asset_path(lecture.pdf_path)
    pptx_path = _resolve_lecture_asset_path(lecture.pptx_path)
    if not pdf_path.exists():
        return None, None, f"missing PDF asset: {pdf_path}"
    return pdf_path, pptx_path, None


async def run_backfill(*, apply: bool) -> int:
    await init_db()

    stats = {
        "lectures_total": 0,
        "lectures_with_enriched": 0,
        "rows_total": 0,
        "rows_needing_update": 0,
        "rows_updated": 0,
        "pptx_candidates": 0,
        "pptx_would_regenerate": 0,
        "pptx_regenerated": 0,
        "pptx_skipped": 0,
        "pptx_failed": 0,
    }
    skipped_sync: list[str] = []
    failed_sync: list[str] = []

    async with AsyncSessionLocal() as db:
        lectures = (await db.execute(select(Lecture).order_by(Lecture.id))).scalars().all()
        stats["lectures_total"] = len(lectures)

        for lecture in lectures:
            enriched_rows = (await db.execute(
                select(EnrichedSlide)
                .where(EnrichedSlide.lecture_id == lecture.id)
                .order_by(EnrichedSlide.slide_number)
            )).scalars().all()
            if not enriched_rows:
                continue

            stats["lectures_with_enriched"] += 1
            stats["rows_total"] += len(enriched_rows)

            normalized_entries: list[dict[str, Any]] = []
            lecture_rows_updated = 0
            for row in enriched_rows:
                normalized = _normalized_payload_from_row(row)
                normalized_entries.append({"slide": int(row.slide_number), **normalized})

                if _row_needs_update(row, normalized):
                    stats["rows_needing_update"] += 1
                    if apply:
                        row.summary = normalized["summary"]
                        row.slide_content = normalized["slide_content"]
                        row.lecturer_additions = normalized["lecturer_additions"]
                        row.key_takeaways = normalized["key_takeaways"]
                        stats["rows_updated"] += 1
                        lecture_rows_updated += 1

            if apply and lecture_rows_updated > 0:
                await db.commit()

            pdf_path, pptx_path, skip_reason = _pptx_sync_paths(lecture)
            if skip_reason:
                stats["pptx_skipped"] += 1
                skipped_sync.append(
                    f"lecture_id={lecture.id} name={lecture.name!r}: {skip_reason}"
                )
                continue

            stats["pptx_candidates"] += 1
            if not apply:
                stats["pptx_would_regenerate"] += 1
                continue

            assert pdf_path is not None and pptx_path is not None
            pptx_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                await asyncio.to_thread(
                    generate_presentation_from_enhanced,
                    str(pdf_path),
                    normalized_entries,
                    str(pptx_path),
                )
                stats["pptx_regenerated"] += 1
            except Exception as exc:
                stats["pptx_failed"] += 1
                failed_sync.append(
                    f"lecture_id={lecture.id} name={lecture.name!r}: {exc}"
                )

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\nBackfill mode: {mode}")
    print(f"Lectures total: {stats['lectures_total']}")
    print(f"Lectures with enriched notes: {stats['lectures_with_enriched']}")
    print(f"Enriched rows total: {stats['rows_total']}")
    print(f"Rows needing canonical update: {stats['rows_needing_update']}")
    if apply:
        print(f"Rows updated: {stats['rows_updated']}")
    print(f"PPTX candidates: {stats['pptx_candidates']}")
    if apply:
        print(f"PPTX regenerated: {stats['pptx_regenerated']}")
    else:
        print(f"PPTX would regenerate: {stats['pptx_would_regenerate']}")
    print(f"PPTX skipped: {stats['pptx_skipped']}")
    print(f"PPTX failed: {stats['pptx_failed']}")

    if skipped_sync:
        print("\nSkipped PPTX sync:")
        for line in skipped_sync:
            print(f"  - {line}")

    if failed_sync:
        print("\nFailed PPTX sync:")
        for line in failed_sync:
            print(f"  - {line}")

    return 1 if failed_sync else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill enriched note formatting and optionally regenerate lecture PPTX files."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply DB updates and regenerate PPTX files (default is dry-run).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(asyncio.run(run_backfill(apply=args.apply)))
