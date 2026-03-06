import os
import sys
import types
import unittest
from importlib.util import find_spec
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")


if find_spec("anthropic") is None:  # pragma: no cover - local test env helper
    anthropic_stub = types.ModuleType("anthropic")

    class _DummyAnthropic:
        def __init__(self, *args, **kwargs):
            pass

    class _DummyRateLimitError(Exception):
        pass

    class _DummyOverloadedError(Exception):
        pass

    anthropic_stub.Anthropic = _DummyAnthropic
    anthropic_stub.RateLimitError = _DummyRateLimitError
    anthropic_stub.OverloadedError = _DummyOverloadedError
    sys.modules.setdefault("anthropic", anthropic_stub)

if find_spec("groq") is None:  # pragma: no cover - local test env helper
    groq_stub = types.ModuleType("groq")
    groq_stub.Groq = type("Groq", (), {})
    sys.modules.setdefault("groq", groq_stub)

if find_spec("pdfplumber") is None:  # pragma: no cover - local test env helper
    pdfplumber_stub = types.ModuleType("pdfplumber")

    def _missing_pdf_open(*args, **kwargs):
        raise RuntimeError("pdfplumber.open should not be called in batching tests")

    pdfplumber_stub.open = _missing_pdf_open
    sys.modules.setdefault("pdfplumber", pdfplumber_stub)

try:  # pragma: no cover - local test env helper
    import scripts.enrich as _enrich_module

    if getattr(_enrich_module, "anthropic", None) is None and "anthropic" in sys.modules:
        _enrich_module.anthropic = sys.modules["anthropic"]
except Exception:
    pass

PIPELINE_IMPORT_ERROR: Exception | None = None
try:
    import pipeline as pipeline_module
except ModuleNotFoundError:
    try:
        import backend.pipeline as pipeline_module
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency missing in minimal envs
        pipeline_module = None
        PIPELINE_IMPORT_ERROR = exc

MAIN_IMPORT_ERROR: Exception | None = None
try:
    from backend import main as main_module
except Exception as exc:  # pragma: no cover - dependency missing in minimal envs
    main_module = None
    MAIN_IMPORT_ERROR = exc

PIPELINE_MODULE_NAME = pipeline_module.__name__ if pipeline_module is not None else "backend.pipeline"
MAIN_MODULE_NAME = main_module.__name__ if main_module is not None else "backend.main"


def _fake_enriched_entry(slide_num: int) -> dict:
    return {
        "slide": slide_num,
        "summary": f"Slide {slide_num} sammanfattar huvudpoangen tydligt.",
        "slide_content": (
            f"- **Begrepp {slide_num}** forklarar den centrala iden pa sliden\n"
            f"- **Exempel {slide_num}** visar hur konceptet anvands i praktiken"
        ),
        "lecturer_additions": "",
        "key_takeaways": [
            f"**Begrepp {slide_num}** ar viktigt for att forsta sammanhanget",
            f"**Exempel {slide_num}** knyter teorin till praktisk anvandning",
        ],
    }


@unittest.skipIf(
    pipeline_module is None,
    f"pipeline module unavailable in this environment: {PIPELINE_IMPORT_ERROR}",
)
class PipelineBatchingTests(unittest.TestCase):
    def test_pipeline_batches_slides_but_emits_per_slide_events(self) -> None:
        slides = [
            {"slide": 1, "text": "Slide 1"},
            {"slide": 2, "text": "Slide 2"},
            {"slide": 3, "text": "Slide 3"},
        ]
        transcript = [
            {"text": "Segment 0"},
            {"text": "Segment 1"},
            {"text": "Segment 2"},
        ]
        alignment = [
            {"slide": 1, "start_segment": 0, "end_segment": 0},
            {"slide": 2, "start_segment": 1, "end_segment": 1},
            {"slide": 3, "start_segment": 2, "end_segment": 2},
        ]
        batch_calls: list[list[int]] = []
        progress_messages: list[str] = []
        slide_events: list[tuple[int, dict]] = []

        def fake_batch(slides_with_transcripts, **kwargs):
            slide_nums = [int(slide["slide"]) for slide, _ in slides_with_transcripts]
            batch_calls.append(slide_nums)
            entries = [_fake_enriched_entry(slide_num) for slide_num in slide_nums]
            metrics = {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "retries": 0,
                "fallbacks": 0,
                "duration_ms": 1,
                "failure_reason_counts": {
                    "truncated_json": 0,
                    "empty_payload": 0,
                    "connection_error": 0,
                    "other_error": 0,
                },
            }
            return entries, metrics

        def emit(stage: str, message: str, pct: int) -> None:
            progress_messages.append(message)

        with (
            patch.object(pipeline_module, "ENRICH_BATCH_SIZE", 2),
            patch.object(pipeline_module, "ENRICH_MAX_WORKERS", 1),
            patch(f"{PIPELINE_MODULE_NAME}.enrich_slides_batch_notes", side_effect=fake_batch),
        ):
            results = pipeline_module.enrich(
                slides,
                transcript,
                alignment,
                emit=emit,
                on_slide_enriched=lambda slide_num, payload: slide_events.append((slide_num, payload)),
            )

        self.assertEqual(batch_calls, [[1, 2], [3]])
        self.assertEqual([entry["slide"] for entry in results], [1, 2, 3])
        self.assertEqual([slide_num for slide_num, _ in slide_events], [1, 2, 3])
        self.assertEqual(
            [message for message in progress_messages if message.startswith("✅ Slide")],
            [
                "✅ Slide 1 done (1/3)",
                "✅ Slide 2 done (2/3)",
                "✅ Slide 3 done (3/3)",
            ],
        )

    def test_pipeline_keeps_single_slide_calls_when_batch_size_is_one(self) -> None:
        slides = [
            {"slide": 1, "text": "Slide 1"},
            {"slide": 2, "text": "Slide 2"},
        ]
        transcript = [
            {"text": "Segment 0"},
            {"text": "Segment 1"},
        ]
        alignment = [
            {"slide": 1, "start_segment": 0, "end_segment": 0},
            {"slide": 2, "start_segment": 1, "end_segment": 1},
        ]
        batch_calls: list[list[int]] = []

        def fake_batch(slides_with_transcripts, **kwargs):
            slide_nums = [int(slide["slide"]) for slide, _ in slides_with_transcripts]
            batch_calls.append(slide_nums)
            entries = [_fake_enriched_entry(slide_num) for slide_num in slide_nums]
            metrics = {
                "input_tokens": 5,
                "output_tokens": 2,
                "total_tokens": 7,
                "retries": 0,
                "fallbacks": 0,
                "duration_ms": 1,
                "failure_reason_counts": {
                    "truncated_json": 0,
                    "empty_payload": 0,
                    "connection_error": 0,
                    "other_error": 0,
                },
            }
            return entries, metrics

        with (
            patch.object(pipeline_module, "ENRICH_BATCH_SIZE", 1),
            patch.object(pipeline_module, "ENRICH_MAX_WORKERS", 1),
            patch(f"{PIPELINE_MODULE_NAME}.enrich_slides_batch_notes", side_effect=fake_batch),
        ):
            results = pipeline_module.enrich(slides, transcript, alignment)

        self.assertEqual(batch_calls, [[1], [2]])
        self.assertEqual([entry["slide"] for entry in results], [1, 2])


@unittest.skipIf(
    main_module is None,
    f"backend.main unavailable in this environment: {MAIN_IMPORT_ERROR}",
)
class RegenerationBatchingTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_notes_for_slides_preserves_input_order_from_batch_results(self) -> None:
        slides_with_transcripts = [
            ({"slide": 1, "text": "Slide 1"}, "Transcript 1"),
            ({"slide": 2, "text": "Slide 2"}, "Transcript 2"),
        ]
        batch_results = [
            _fake_enriched_entry(2),
            _fake_enriched_entry(1),
        ]

        with (
            patch.object(main_module, "DISABLE_EXTERNAL_AI", False),
            patch(
                f"{MAIN_MODULE_NAME}.run_in_threadpool",
                new=AsyncMock(return_value=batch_results),
            ) as pool_mock,
        ):
            results = await main_module.generate_notes_for_slides(
                slides_with_transcripts,
                course_context="Course Context",
            )

        pool_mock.assert_awaited_once()
        self.assertEqual(pool_mock.await_args.args[0], main_module.enrich_slides_batch_notes)
        self.assertEqual(pool_mock.await_args.args[1], slides_with_transcripts)
        self.assertEqual(pool_mock.await_args.kwargs["course_context"], "Course Context")
        self.assertEqual([entry["slide"] for entry in results], [1, 2])
        self.assertEqual(results[0]["summary"], _fake_enriched_entry(1)["summary"])


if __name__ == "__main__":
    unittest.main()
