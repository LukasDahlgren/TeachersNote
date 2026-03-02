import os
import unittest
from types import SimpleNamespace

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
    is_approved: bool = False,
    is_deleted: bool = False,
    uploaded_by: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        is_approved=is_approved,
        is_deleted=is_deleted,
        uploaded_by=uploaded_by,
    )


@unittest.skipUnless(HELPERS_AVAILABLE, f"visibility helpers unavailable: {IMPORT_ERROR}")
class LectureVisibilityTests(unittest.TestCase):
    def test_non_admin_can_view_approved_lecture(self):
        lecture = _lecture(is_approved=True, uploaded_by="alice")
        self.assertTrue(can_view_lecture(user_id="bob", lecture=lecture, is_admin=False))

    def test_non_admin_can_view_own_pending_lecture(self):
        lecture = _lecture(is_approved=False, uploaded_by="bob")
        self.assertTrue(can_view_lecture(user_id="bob", lecture=lecture, is_admin=False))

    def test_non_admin_cannot_view_other_users_pending_lecture(self):
        lecture = _lecture(is_approved=False, uploaded_by="alice")
        self.assertFalse(can_view_lecture(user_id="bob", lecture=lecture, is_admin=False))

    def test_non_admin_cannot_view_deleted_lecture(self):
        lecture = _lecture(is_approved=True, is_deleted=True, uploaded_by="alice")
        self.assertFalse(can_view_lecture(user_id="alice", lecture=lecture, is_admin=False))

    def test_admin_can_view_deleted_pending_lecture(self):
        lecture = _lecture(is_approved=False, is_deleted=True, uploaded_by="alice")
        self.assertTrue(can_view_lecture(user_id="bob", lecture=lecture, is_admin=True))

    def test_assert_user_can_view_lecture_raises_404_for_hidden_lecture(self):
        lecture = _lecture(is_approved=False, uploaded_by="alice")
        with self.assertRaises(Exception) as ctx:
            assert_user_can_view_lecture(user_id="bob", lecture=lecture, is_admin=False)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)


if __name__ == "__main__":
    unittest.main()
