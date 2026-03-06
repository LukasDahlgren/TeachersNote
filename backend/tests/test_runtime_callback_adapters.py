import io
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


class _AsyncSessionContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyUploadFile:
    def __init__(self, filename: str, payload: bytes) -> None:
        self.filename = filename
        self.file = io.BytesIO(payload)

    async def read(self) -> bytes:
        return self.file.read()

    async def seek(self, offset: int) -> None:
        self.file.seek(offset)


@unittest.skipUnless(HELPERS_AVAILABLE, f"runtime adapter helpers unavailable: {IMPORT_ERROR}")
class RuntimeCallbackAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_process_job_wrapper_injects_runtime_dependencies(self) -> None:
        assert backend_main is not None
        runner = AsyncMock(return_value=None)
        with patch.object(backend_main._upload_workflow_service, "_run_process_job", runner):
            await backend_main._run_process_job(
                "job-1",
                pdf_path=Path("/tmp/slides.pdf"),
                audio_path=Path("/tmp/audio.wav"),
                lecture_name="IB133N-lecture-14-2026",
                course_id="IB133N",
                naming_kind="lecture",
                naming_lecture="14",
                naming_year="2026",
                upload_courseid_raw="IB133N",
                upload_kind_raw="lecture",
                upload_lecture_raw="14",
                upload_year_raw="2026",
                temporary_name_seed=None,
                pptx_path=Path("/tmp/out.pptx"),
                saved_pdf_path=Path("/tmp/saved.pdf"),
                user_id="alice",
                pdf_hash="abc123",
                course_context="Algorithms",
                custom_name="Lecture 14",
            )

        kwargs = runner.await_args.kwargs
        self.assertIs(kwargs["update_upload_job"], backend_main._update_upload_job)
        self.assertIs(kwargs["add_upload_job_raw_event"], backend_main._add_upload_job_raw_event)
        self.assertIs(kwargs["async_session_factory"], backend_main.AsyncSessionLocal)

    async def test_run_regenerate_notes_job_wrapper_injects_runtime_dependencies(self) -> None:
        assert backend_main is not None
        runner = AsyncMock(return_value=None)
        with patch.object(backend_main._regeneration_service, "_run_regenerate_notes_job", runner):
            await backend_main._run_regenerate_notes_job("job-2", 44)

        kwargs = runner.await_args.kwargs
        self.assertIs(kwargs["update_job"], backend_main._update_job)
        self.assertIs(kwargs["async_session_factory"], backend_main.AsyncSessionLocal)

    async def test_delete_guard_wrapper_injects_runtime_dependencies(self) -> None:
        assert backend_main is not None
        guard = AsyncMock(return_value=None)
        with patch.object(backend_main._lecture_access_service, "_assert_lecture_can_be_permanently_deleted", guard):
            await backend_main._assert_lecture_can_be_permanently_deleted(12)

        kwargs = guard.await_args.kwargs
        self.assertIs(kwargs["get_active_job_for_lecture"], backend_main._get_active_job_for_lecture)
        self.assertIs(kwargs["get_active_upload_job_for_lecture"], backend_main._get_active_upload_job_for_lecture)

    async def test_start_process_job_schedules_background_task_with_compat_signature(self) -> None:
        assert backend_main is not None
        current_user = SimpleNamespace(uuid="alice")
        raw = SimpleNamespace(courseid=None, kind=None, lecture=None, year=None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            uploads_dir = root / "uploads"
            uploads_dir.mkdir()
            saved_pdf_path = root / "source_pdfs" / "saved.pdf"
            saved_pdf_path.parent.mkdir(parents=True)
            submission_naming = SimpleNamespace(
                lecture_name="pending-upload",
                courseid=None,
                kind=None,
                lecture=None,
                year=None,
                raw=raw,
                temporary_name_seed="pending-upload",
                pptx_path=root / "generated" / "out.pptx",
                saved_pdf_path=saved_pdf_path,
            )
            created: list[object] = []

            def fake_create_task(coro):
                created.append(coro)
                coro.close()
                return SimpleNamespace()

            with patch.object(backend_main, "UPLOADS_DIR", uploads_dir), \
                patch.object(backend_main, "_resolve_upload_submission_naming", return_value=submission_naming), \
                patch.object(backend_main, "_cleanup_expired_upload_jobs", AsyncMock()), \
                patch.object(backend_main, "_get_active_upload_job", AsyncMock(return_value=None)), \
                patch.object(backend_main, "_resolve_recording_source_or_400", return_value=("file", None)), \
                patch.object(backend_main, "AsyncSessionLocal", lambda: _AsyncSessionContext(SimpleNamespace())), \
                patch.object(backend_main, "_is_admin", AsyncMock(return_value=True)), \
                patch.object(backend_main, "_create_upload_job", AsyncMock(return_value={"job_id": "job-1"})), \
                patch.object(backend_main, "_update_upload_job", AsyncMock()), \
                patch.object(backend_main, "_get_upload_job_snapshot", AsyncMock(return_value={"job_id": "job-1"})), \
                patch.object(backend_main, "_upload_job_public_state", side_effect=lambda snapshot: snapshot), \
                patch.object(backend_main.asyncio, "create_task", side_effect=fake_create_task):
                result = await backend_main.start_process_job(
                    pdf=_DummyUploadFile("slides.pdf", b"%PDF-1.4"),
                    audio=_DummyUploadFile("audio.wav", b"RIFF"),
                    audio_url=None,
                    courseid=None,
                    kind=None,
                    lecture=None,
                    year=None,
                    course_context=None,
                    custom_name=None,
                    current_user=current_user,
                )

        self.assertEqual(result["job_id"], "job-1")
        self.assertEqual(len(created), 1)

    async def test_start_regenerate_notes_job_schedules_background_task_with_compat_signature(self) -> None:
        assert backend_main is not None
        current_user = SimpleNamespace(uuid="alice")
        lecture = SimpleNamespace(id=44)
        created: list[object] = []

        def fake_create_task(coro):
            created.append(coro)
            coro.close()
            return SimpleNamespace()

        with patch.object(backend_main, "_cleanup_expired_jobs", AsyncMock()), \
            patch.object(backend_main, "get_lecture_or_404", AsyncMock(return_value=lecture)), \
            patch.object(backend_main, "_is_admin", AsyncMock(return_value=False)), \
            patch.object(backend_main, "assert_user_can_view_lecture", AsyncMock()), \
            patch.object(backend_main, "_get_active_job_for_lecture", AsyncMock(return_value=None)), \
            patch.object(backend_main, "_load_regeneration_context", AsyncMock(return_value={"align_rows": [], "enriched_by_slide": {}})), \
            patch.object(backend_main, "_build_regeneration_targets", return_value=[]), \
            patch.object(backend_main, "_create_job", AsyncMock(return_value={"job_id": "regen-1"})), \
            patch.object(backend_main, "_job_public_state", side_effect=lambda job: job), \
            patch.object(backend_main.asyncio, "create_task", side_effect=fake_create_task):
            result = await backend_main.start_regenerate_notes_job(
                44,
                db=SimpleNamespace(),
                current_user=current_user,
            )

        self.assertEqual(result["job_id"], "regen-1")
        self.assertEqual(len(created), 1)

    async def test_trash_lecture_returns_409_when_upload_job_is_active(self) -> None:
        assert backend_main is not None
        lecture = SimpleNamespace(id=9)

        with patch.object(backend_main, "_require_admin_user_or_403", AsyncMock()), \
            patch.object(backend_main, "get_lecture_or_404", AsyncMock(return_value=lecture)), \
            patch.object(backend_main, "_get_active_job_for_lecture", AsyncMock(return_value=None)), \
            patch.object(backend_main, "_get_active_upload_job_for_lecture", AsyncMock(return_value={"job_id": "upload-1"})):
            with self.assertRaises(Exception) as ctx:
                await backend_main.trash_lecture(
                    9,
                    db=SimpleNamespace(),
                    current_user=SimpleNamespace(uuid="admin"),
                )

        self.assertEqual(getattr(ctx.exception, "status_code", None), 409)

    async def test_reject_lecture_returns_409_when_regeneration_job_is_active(self) -> None:
        assert backend_main is not None
        lecture = SimpleNamespace(id=10)

        with patch.object(backend_main, "_is_admin", AsyncMock(return_value=True)), \
            patch.object(backend_main, "get_lecture_or_404", AsyncMock(return_value=lecture)), \
            patch.object(backend_main, "_get_active_job_for_lecture", AsyncMock(return_value={"job_id": "regen-1"})), \
            patch.object(backend_main, "_get_active_upload_job_for_lecture", AsyncMock(return_value=None)):
            with self.assertRaises(Exception) as ctx:
                await backend_main.reject_lecture(
                    10,
                    db=SimpleNamespace(),
                    current_user=SimpleNamespace(uuid="admin"),
                )

        self.assertEqual(getattr(ctx.exception, "status_code", None), 409)


if __name__ == "__main__":
    unittest.main()
