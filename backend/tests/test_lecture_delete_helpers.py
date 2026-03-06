import os
import tempfile
import unittest
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("API_KEY", "test-api-key")

HELPERS_AVAILABLE = True
IMPORT_ERROR: Exception | None = None
try:
    backend_main = importlib.import_module("backend.main")
except Exception as exc:
    IMPORT_ERROR = exc
    HELPERS_AVAILABLE = False
    backend_main = None  # type: ignore[assignment]


@unittest.skipUnless(HELPERS_AVAILABLE, f"delete helpers unavailable: {IMPORT_ERROR}")
class LectureDeleteHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_permanently_delete_lecture_removes_assets_and_commits(self) -> None:
        assert backend_main is not None
        with tempfile.TemporaryDirectory() as tmp:
            backend_dir = Path(tmp)
            uploads_dir = backend_dir / "uploads"
            generated_dir = backend_dir / "generated"
            source_pdfs_dir = backend_dir / "source_pdfs"
            uploads_dir.mkdir()
            generated_dir.mkdir()
            source_pdfs_dir.mkdir()

            pptx_path = generated_dir / "lecture.pptx"
            pdf_path = source_pdfs_dir / "lecture.pdf"
            pptx_path.write_bytes(b"pptx")
            pdf_path.write_bytes(b"pdf")

            lecture = SimpleNamespace(
                id=7,
                pptx_path="generated/lecture.pptx",
                pdf_path="source_pdfs/lecture.pdf",
            )
            db = SimpleNamespace(
                delete=AsyncMock(),
                commit=AsyncMock(),
                rollback=AsyncMock(),
            )

            with patch.object(backend_main, "BACKEND_DIR", backend_dir), patch.object(backend_main, "UPLOADS_DIR", uploads_dir):
                await backend_main._permanently_delete_lecture(db, lecture)

            self.assertFalse(pptx_path.exists())
            self.assertFalse(pdf_path.exists())
            db.delete.assert_awaited_once_with(lecture)
            db.commit.assert_awaited_once()
            db.rollback.assert_not_awaited()

    async def test_permanently_delete_lecture_restores_assets_when_commit_fails(self) -> None:
        assert backend_main is not None
        with tempfile.TemporaryDirectory() as tmp:
            backend_dir = Path(tmp)
            uploads_dir = backend_dir / "uploads"
            generated_dir = backend_dir / "generated"
            source_pdfs_dir = backend_dir / "source_pdfs"
            uploads_dir.mkdir()
            generated_dir.mkdir()
            source_pdfs_dir.mkdir()

            pptx_path = generated_dir / "lecture.pptx"
            pdf_path = source_pdfs_dir / "lecture.pdf"
            pptx_path.write_bytes(b"pptx")
            pdf_path.write_bytes(b"pdf")

            lecture = SimpleNamespace(
                id=8,
                pptx_path="generated/lecture.pptx",
                pdf_path="source_pdfs/lecture.pdf",
            )
            db = SimpleNamespace(
                delete=AsyncMock(),
                commit=AsyncMock(side_effect=RuntimeError("commit failed")),
                rollback=AsyncMock(),
            )

            with patch.object(backend_main, "BACKEND_DIR", backend_dir), patch.object(backend_main, "UPLOADS_DIR", uploads_dir):
                with self.assertRaises(Exception) as ctx:
                    await backend_main._permanently_delete_lecture(db, lecture)

            self.assertEqual(getattr(ctx.exception, "status_code", None), 500)
            self.assertTrue(pptx_path.exists())
            self.assertTrue(pdf_path.exists())
            db.delete.assert_awaited_once_with(lecture)
            db.commit.assert_awaited_once()
            db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
