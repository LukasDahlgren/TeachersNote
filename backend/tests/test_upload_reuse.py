import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("API_KEY", "test-api-key")

HELPERS_AVAILABLE = True
IMPORT_ERROR: Exception | None = None
try:
    from backend.main import (
        _assert_user_can_view_upload_job,
        _find_reusable_lecture_by_pdf_hash,
    )
except Exception as exc:
    IMPORT_ERROR = exc
    HELPERS_AVAILABLE = False
    _assert_user_can_view_upload_job = None  # type: ignore[assignment]
    _find_reusable_lecture_by_pdf_hash = None  # type: ignore[assignment]


def _lecture(lecture_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=lecture_id)


def _db_with_lectures(lectures: list[SimpleNamespace]) -> SimpleNamespace:
    rows = SimpleNamespace(all=lambda: lectures)
    result = SimpleNamespace(scalars=lambda: rows)
    return SimpleNamespace(execute=AsyncMock(return_value=result))


@unittest.skipUnless(HELPERS_AVAILABLE, f"reuse helpers unavailable: {IMPORT_ERROR}")
class UploadReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_reusable_lookup_returns_none_for_missing_hash(self):
        db = _db_with_lectures([])
        lecture = await _find_reusable_lecture_by_pdf_hash(db, pdf_hash=None)
        self.assertIsNone(lecture)
        db.execute.assert_not_awaited()

    async def test_reusable_lookup_returns_first_visible_candidate(self):
        db = _db_with_lectures([_lecture(1), _lecture(2)])
        with patch("backend.main._lecture_has_visible_pptx", side_effect=lambda lecture: lecture.id == 2):
            lecture = await _find_reusable_lecture_by_pdf_hash(db, pdf_hash="abc123")
        self.assertIsNotNone(lecture)
        self.assertEqual(getattr(lecture, "id", None), 2)

    async def test_reusable_lookup_returns_none_when_all_candidates_are_hidden(self):
        db = _db_with_lectures([_lecture(1), _lecture(2)])
        with patch("backend.main._lecture_has_visible_pptx", return_value=False):
            lecture = await _find_reusable_lecture_by_pdf_hash(db, pdf_hash="abc123")
        self.assertIsNone(lecture)

    def test_upload_job_owner_check_rejects_other_user(self):
        with self.assertRaises(Exception) as ctx:
            _assert_user_can_view_upload_job(
                user_id="bob",
                job={"job_id": "job-1", "user_id": "alice"},
            )
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)


if __name__ == "__main__":
    unittest.main()
