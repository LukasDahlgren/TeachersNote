import socket
import unittest

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    HAS_HTTPX = False

try:
    from backend.chatbot import (
        SYSTEM_PROMPT,
        ChatServiceUnavailableError,
        _format_provider_connectivity_error,
        _reraise_if_provider_unreachable,
        build_lecture_context,
    )
except ImportError:
    from chatbot import (
        SYSTEM_PROMPT,
        ChatServiceUnavailableError,
        _format_provider_connectivity_error,
        _reraise_if_provider_unreachable,
        build_lecture_context,
    )


@unittest.skipUnless(HAS_HTTPX, "httpx not installed")
class ChatbotErrorHandlingTests(unittest.TestCase):
    def test_dns_lookup_failure_maps_to_clear_message(self) -> None:
        exc = httpx.ConnectError("[Errno -2] Name or service not known")
        exc.__cause__ = socket.gaierror(-2, "Name or service not known")

        message = _format_provider_connectivity_error("Groq", exc)

        self.assertIsNotNone(message)
        self.assertIn("DNS lookup failed", message)
        self.assertIn("Groq chat", message)

    def test_connect_error_without_dns_maps_to_provider_unreachable(self) -> None:
        message = _format_provider_connectivity_error("Groq", httpx.ConnectError("Connection refused"))

        self.assertIsNotNone(message)
        self.assertIn("could not be reached", message)

    def test_unrelated_error_is_not_rewritten(self) -> None:
        self.assertIsNone(_format_provider_connectivity_error("Groq", ValueError("bad input")))

    def test_reraise_uses_service_unavailable_error(self) -> None:
        with self.assertRaises(ChatServiceUnavailableError):
            _reraise_if_provider_unreachable("Groq", httpx.ConnectError("Connection refused"))


class BuildLectureContextTests(unittest.TestCase):
    _SLIDES = [
        {"slide": 1, "text": "DATABASMETODIK / Structured Query Language / SQL"},
        {"slide": 2, "text": "SELECT * FROM students WHERE grade > 3"},
    ]
    _TRANSCRIPT = [
        {"start": 0.0, "end": 5.0, "text": "Welcome to the database lecture."},
        {"start": 5.0, "end": 10.0, "text": "Today we cover SQL basics."},
        {"start": 10.0, "end": 15.0, "text": "Let's look at SELECT statements."},
    ]
    _ALIGNMENT = [
        {"slide": 1, "start_segment": 0, "end_segment": 1},
        {"slide": 2, "start_segment": 2, "end_segment": 2},
    ]

    def test_includes_raw_text_from_all_slides(self) -> None:
        ctx = build_lecture_context(self._SLIDES)
        self.assertIn("DATABASMETODIK / Structured Query Language / SQL", ctx)
        self.assertIn("SELECT * FROM students WHERE grade > 3", ctx)

    def test_slide_headers_are_present(self) -> None:
        ctx = build_lecture_context(self._SLIDES)
        self.assertIn("--- Slide 1 ---", ctx)
        self.assertIn("--- Slide 2 ---", ctx)

    def test_includes_transcript_under_matching_slide(self) -> None:
        ctx = build_lecture_context(self._SLIDES, transcript=self._TRANSCRIPT, alignment=self._ALIGNMENT)
        self.assertIn("Welcome to the database lecture.", ctx)
        self.assertIn("Let's look at SELECT statements.", ctx)

    def test_transcript_appears_after_its_slide_header(self) -> None:
        ctx = build_lecture_context(self._SLIDES, transcript=self._TRANSCRIPT, alignment=self._ALIGNMENT)
        slide1_pos = ctx.index("--- Slide 1 ---")
        slide2_pos = ctx.index("--- Slide 2 ---")
        transcript1_pos = ctx.index("Welcome to the database lecture.")
        transcript2_pos = ctx.index("Let's look at SELECT statements.")
        self.assertGreater(transcript1_pos, slide1_pos)
        self.assertLess(transcript1_pos, slide2_pos)
        self.assertGreater(transcript2_pos, slide2_pos)

    def test_does_not_use_enhanced_fields(self) -> None:
        # enhanced-only fields must not appear in context
        ctx = build_lecture_context(self._SLIDES)
        self.assertNotIn("summary:", ctx.lower())
        self.assertNotIn("key takeaways", ctx.lower())
        self.assertNotIn("lecturer notes", ctx.lower())

    def test_no_transcript_when_not_provided(self) -> None:
        ctx = build_lecture_context(self._SLIDES)
        self.assertNotIn("Transcript:", ctx)

    def test_sql_fixture_contains_expected_strings(self) -> None:
        ctx = build_lecture_context(self._SLIDES, transcript=self._TRANSCRIPT, alignment=self._ALIGNMENT)
        self.assertIn("DATABASMETODIK", ctx)
        self.assertIn("SQL", ctx)
        self.assertNotIn("energy", ctx.lower())
        self.assertNotIn("resource efficiency", ctx.lower())


class SystemPromptTests(unittest.TestCase):
    def test_requires_slide_citations(self) -> None:
        self.assertIn("[Slide", SYSTEM_PROMPT)

    def test_requires_explicit_uncertainty_phrase(self) -> None:
        self.assertIn("det framgår inte av materialet", SYSTEM_PROMPT)

    def test_prohibits_inference_outside_material(self) -> None:
        lower = SYSTEM_PROMPT.lower()
        self.assertTrue(
            "not supported" in lower or "not present" in lower or "not covered" in lower
            or "only from" in lower or "do not infer" in lower,
        )


if __name__ == "__main__":
    unittest.main()
