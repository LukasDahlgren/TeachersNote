import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("API_KEY", "test-api-key")

HELPERS_AVAILABLE = True
IMPORT_ERROR: Exception | None = None
try:
    from backend.main import assert_user_can_view_lecture, can_view_lecture
except Exception as exc:
    IMPORT_ERROR = exc
    HELPERS_AVAILABLE = False
    assert_user_can_view_lecture = None  # type: ignore[assignment]
    can_view_lecture = None  # type: ignore[assignment]


def _lecture(
    *,
    lecture_id: int = 1,
    is_approved: bool = False,
    is_deleted: bool = False,
    uploaded_by: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=lecture_id,
        is_approved=is_approved,
        is_deleted=is_deleted,
        uploaded_by=uploaded_by,
    )


@unittest.skipUnless(HELPERS_AVAILABLE, f"visibility helpers unavailable: {IMPORT_ERROR}")
class LectureVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def _db(self, *, has_access: bool = False):
        result = SimpleNamespace(scalar_one_or_none=lambda: 1 if has_access else None)
        return SimpleNamespace(execute=AsyncMock(return_value=result))

    async def test_non_admin_cannot_view_other_users_approved_lecture_without_access(self):
        lecture = _lecture(is_approved=True, uploaded_by="alice")
        self.assertFalse(await can_view_lecture(self._db(), user_id="bob", lecture=lecture, is_admin=False))

    async def test_non_admin_can_view_own_pending_lecture(self):
        lecture = _lecture(is_approved=False, uploaded_by="bob")
        self.assertTrue(await can_view_lecture(self._db(), user_id="bob", lecture=lecture, is_admin=False))

    async def test_non_admin_can_view_other_users_lecture_with_explicit_access(self):
        lecture = _lecture(is_approved=True, uploaded_by="alice")
        self.assertTrue(await can_view_lecture(self._db(has_access=True), user_id="bob", lecture=lecture, is_admin=False))

    async def test_non_admin_cannot_view_deleted_lecture_even_with_access(self):
        lecture = _lecture(is_approved=True, is_deleted=True, uploaded_by="alice")
        self.assertFalse(await can_view_lecture(self._db(has_access=True), user_id="bob", lecture=lecture, is_admin=False))

    async def test_admin_can_view_deleted_pending_lecture(self):
        lecture = _lecture(is_approved=False, is_deleted=True, uploaded_by="alice")
        self.assertTrue(await can_view_lecture(self._db(), user_id="bob", lecture=lecture, is_admin=True))

    async def test_assert_user_can_view_lecture_raises_404_for_hidden_lecture(self):
        lecture = _lecture(is_approved=False, uploaded_by="alice")
        with self.assertRaises(Exception) as ctx:
            await assert_user_can_view_lecture(self._db(), user_id="bob", lecture=lecture, is_admin=False)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)


if __name__ == "__main__":
    unittest.main()
