import time
import unittest
from pathlib import Path
from unittest.mock import patch

PIPELINE_IMPORT_ERROR: Exception | None = None
try:
    import pipeline as pipeline_module
except ModuleNotFoundError:
    try:
        import backend.pipeline as pipeline_module
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency missing in minimal envs
        pipeline_module = None
        PIPELINE_IMPORT_ERROR = exc

MODULE_NAME = pipeline_module.__name__ if pipeline_module is not None else "backend.pipeline"


@unittest.skipIf(
    pipeline_module is None,
    f"pipeline module unavailable in this environment: {PIPELINE_IMPORT_ERROR}",
)
class TranscribeParallelTests(unittest.TestCase):
    def test_parallel_chunk_results_are_merged_in_time_order(self) -> None:
        def fake_transcribe(chunk_path: Path, *, emit=None, chunk_label=None):
            idx = int(chunk_path.stem.split("-")[1])
            if idx == 0:
                time.sleep(0.03)
            elif idx == 1:
                time.sleep(0.01)
            return [
                {"start": 0.3, "end": 0.6, "text": f"chunk-{idx}-late"},
                {"start": 0.1, "end": 0.2, "text": f"chunk-{idx}-early"},
            ]

        with (
            patch.object(pipeline_module, "TRANSCRIBE_PARALLEL_WORKERS", 3),
            patch.object(pipeline_module, "TRANSCRIBE_PARALLEL_MIN_CHUNKS", 2),
            patch(f"{MODULE_NAME}.subprocess.run", return_value=None),
            patch(f"{MODULE_NAME}._transcribe_mp3_file_with_retries", side_effect=fake_transcribe),
        ):
            segments = pipeline_module._transcribe_mp3_in_chunks(
                mp3_path=Path("/tmp/fake.mp3"),
                duration_seconds=12.0,
                chunk_seconds=4,
                emit=None,
            )

        starts = [float(seg["start"]) for seg in segments]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(
            [seg["text"] for seg in segments],
            [
                "chunk-0-early",
                "chunk-0-late",
                "chunk-1-early",
                "chunk-1-late",
                "chunk-2-early",
                "chunk-2-late",
            ],
        )

    def test_sequential_fallback_when_chunk_count_below_min_threshold(self) -> None:
        call_order: list[int] = []

        def fake_transcribe(chunk_path: Path, *, emit=None, chunk_label=None):
            idx = int(chunk_path.stem.split("-")[1])
            call_order.append(idx)
            return [{"start": 0.0, "end": 0.1, "text": f"chunk-{idx}"}]

        with (
            patch.object(pipeline_module, "TRANSCRIBE_PARALLEL_WORKERS", 4),
            patch.object(pipeline_module, "TRANSCRIBE_PARALLEL_MIN_CHUNKS", 5),
            patch(f"{MODULE_NAME}.subprocess.run", return_value=None),
            patch(f"{MODULE_NAME}.ThreadPoolExecutor") as pool_mock,
            patch(f"{MODULE_NAME}._transcribe_mp3_file_with_retries", side_effect=fake_transcribe),
        ):
            segments = pipeline_module._transcribe_mp3_in_chunks(
                mp3_path=Path("/tmp/fake.mp3"),
                duration_seconds=12.0,
                chunk_seconds=4,
                emit=None,
            )

        pool_mock.assert_not_called()
        self.assertEqual(call_order, [0, 1, 2])
        self.assertEqual([seg["text"] for seg in segments], ["chunk-0", "chunk-1", "chunk-2"])

    def test_retry_delay_uses_exponential_backoff_with_jitter(self) -> None:
        with (
            patch.object(pipeline_module, "TRANSCRIBE_RETRY_BASE_DELAY_SECONDS", 2.0),
            patch(f"{MODULE_NAME}.random.uniform", return_value=1.1),
        ):
            delay = pipeline_module._retry_delay_seconds(3)
        self.assertAlmostEqual(delay, 8.8, places=6)

    def test_retry_on_transient_errors_then_success(self) -> None:
        calls = {"count": 0}

        def fake_transcribe(_mp3_path: Path):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("timed out")
            return [{"start": 0.0, "end": 0.1, "text": "ok"}]

        with (
            patch.object(pipeline_module, "TRANSCRIBE_RETRY_ATTEMPTS", 3),
            patch(f"{MODULE_NAME}._transcribe_mp3_file", side_effect=fake_transcribe) as transcribe_mock,
            patch(f"{MODULE_NAME}._retry_delay_seconds", return_value=1.25) as delay_mock,
            patch(f"{MODULE_NAME}.time.sleep") as sleep_mock,
        ):
            result = pipeline_module._transcribe_mp3_file_with_retries(
                Path("/tmp/fake-chunk.mp3"),
                emit=None,
                chunk_label="chunk 1/2",
            )

        self.assertEqual(transcribe_mock.call_count, 2)
        delay_mock.assert_called_once_with(1)
        sleep_mock.assert_called_once_with(1.25)
        self.assertEqual(result, [{"start": 0.0, "end": 0.1, "text": "ok"}])

    def test_413_error_still_bubbles_as_non_retryable(self) -> None:
        class TooLargeError(RuntimeError):
            def __init__(self):
                super().__init__("request too large")
                self.status_code = 413

        with (
            patch.object(pipeline_module, "TRANSCRIBE_RETRY_ATTEMPTS", 3),
            patch(f"{MODULE_NAME}._transcribe_mp3_file", side_effect=TooLargeError()) as transcribe_mock,
            patch(f"{MODULE_NAME}.time.sleep") as sleep_mock,
        ):
            with self.assertRaises(TooLargeError):
                pipeline_module._transcribe_mp3_file_with_retries(
                    Path("/tmp/fake-chunk.mp3"),
                    emit=None,
                    chunk_label="chunk 1/2",
                )

        self.assertEqual(transcribe_mock.call_count, 1)
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
