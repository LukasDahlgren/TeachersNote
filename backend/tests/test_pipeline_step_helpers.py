import tempfile
import unittest
from pathlib import Path

from backend.pipeline_steps.align import sanitize_alignment_boundaries
from backend.pipeline_steps.run import run_pipeline_steps


class AlignStepHelperTests(unittest.TestCase):
    def test_sanitize_fills_missing_slides_and_keeps_order(self) -> None:
        result = sanitize_alignment_boundaries(
            [{"slide": 2, "start_segment": 4}],
            total_slides=3,
            total_segments=8,
        )

        self.assertEqual(
            result,
            [
                {"slide": 1, "start_segment": 0},
                {"slide": 2, "start_segment": 4},
                {"slide": 3, "start_segment": 5},
            ],
        )

    def test_sanitize_rejects_empty_transcript(self) -> None:
        with self.assertRaises(RuntimeError):
            sanitize_alignment_boundaries([], total_slides=1, total_segments=0)


class RunPipelineStepTests(unittest.TestCase):
    def test_run_pipeline_steps_preserves_callback_order_and_output_shape(self) -> None:
        progress_messages: list[tuple[str, str, int]] = []
        on_slides_parsed_calls: list[int] = []
        on_pre_enrich_calls: list[tuple[list[dict], list[dict], list[dict]]] = []
        on_slide_enriched_calls: list[tuple[int, dict]] = []

        slides = [{"slide": 1, "text": "Slide 1"}]
        transcript = [{"start": 0.0, "end": 1.0, "text": "Segment 1"}]
        alignment = [{"slide": 1, "start_segment": 0, "end_segment": 0}]
        enhanced = [{"slide": 1, "summary": "Summary", "slide_content": "", "lecturer_additions": "", "key_takeaways": []}]

        def fake_parse_slides(_pdf_path: str, output_path: str) -> None:
            Path(output_path).write_text('[{"slide": 1, "text": "Slide 1"}]', encoding="utf-8")

        def fake_transcribe(_audio_path: str, _emit):
            return transcript

        def fake_align(_slides: list[dict], _transcript: list[dict], _emit):
            return alignment

        def fake_enrich(
            _slides: list[dict],
            _transcript: list[dict],
            _alignment: list[dict],
            *,
            emit,
            on_slide_enriched,
            course_context,
        ):
            self.assertEqual(course_context, "Course Context")
            on_slide_enriched(1, {"slide": 1, "summary": "Summary"})
            return enhanced

        generated: list[tuple[str, list[dict], str]] = []

        def fake_generate(pdf_path: str, payload: list[dict], output_path: str) -> None:
            generated.append((pdf_path, payload, output_path))

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = str(Path(tmp_dir) / "slides.pdf")
            audio_path = str(Path(tmp_dir) / "recording.wav")
            output_path = str(Path(tmp_dir) / "out.pptx")

            result = run_pipeline_steps(
                pdf_path,
                audio_path,
                output_path,
                emit=lambda stage, message, pct: progress_messages.append((stage, message, pct)),
                on_slides_parsed=lambda count: on_slides_parsed_calls.append(count),
                on_slide_enriched=lambda slide_num, payload: on_slide_enriched_calls.append((slide_num, payload)),
                on_pre_enrich=lambda s, t, a: on_pre_enrich_calls.append((s, t, a)),
                course_context="Course Context",
                emit_progress=lambda emit, stage, message, pct: emit(stage, message, pct),
                transcribe=fake_transcribe,
                align=fake_align,
                enrich=fake_enrich,
                generate_presentation_from_enhanced=fake_generate,
                parse_slides=fake_parse_slides,
            )

        self.assertEqual(on_slides_parsed_calls, [1])
        self.assertEqual(len(on_pre_enrich_calls), 1)
        self.assertEqual(on_slide_enriched_calls, [(1, {"slide": 1, "summary": "Summary"})])
        self.assertEqual(generated, [(pdf_path, enhanced, output_path)])
        self.assertEqual(result["slides"], slides)
        self.assertEqual(result["transcript"], transcript)
        self.assertEqual(result["alignment"], alignment)
        self.assertEqual(result["enhanced"], enhanced)
        self.assertEqual(result["download_url"], f"/download/{Path(output_path).name}")
        self.assertEqual(progress_messages[0], ("parse_slides", "📄 Parsing slides...", 12))
        self.assertEqual(progress_messages[-1], ("generate_pptx", "🎉 Done!", 98))


if __name__ == "__main__":
    unittest.main()
