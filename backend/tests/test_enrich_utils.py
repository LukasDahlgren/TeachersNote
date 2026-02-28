import unittest

from scripts.enrich import (
    is_enriched_payload_invalid,
    normalize_enriched_payload,
    parse_enrichment_response,
    truncate_transcript_for_prompt,
)


class TranscriptTruncationTests(unittest.TestCase):
    def test_under_limit_transcript_keeps_word_sequence(self) -> None:
        transcript = "Detta   ar   ett   kort   test"
        result = truncate_transcript_for_prompt(transcript, max_words=10)
        self.assertEqual(result.split(), transcript.split())

    def test_over_limit_transcript_uses_60_40_head_tail_split(self) -> None:
        words = [f"w{i}" for i in range(1, 21)]
        transcript = " ".join(words)

        result = truncate_transcript_for_prompt(transcript, max_words=10)

        self.assertEqual(len(result.split()), 10)
        self.assertEqual(result.split(), words[:6] + words[-4:])


class EnrichmentPayloadTests(unittest.TestCase):
    def test_payload_aliases_normalize_to_canonical_shape(self) -> None:
        payload = {
            "overview": "Kort sammanfattning.",
            "content": "- Punkt ett\n- Punkt tva",
            "speaker_notes": "Forsta notering\nAndra notering",
            "takeaways": ["A", "B", "C"],
        }

        normalized = normalize_enriched_payload(payload)

        self.assertEqual(normalized["summary"], "Kort sammanfattning.")
        self.assertEqual(normalized["slide_content"], "- Punkt ett\n- Punkt tva")
        self.assertEqual(normalized["lecturer_additions"], "- Forsta notering\n- Andra notering")
        self.assertEqual(normalized["key_takeaways"], ["A", "B", "C"])
        self.assertFalse(is_enriched_payload_invalid(normalized))

    def test_parse_json_response_with_surrounding_text(self) -> None:
        raw = "Svar:\n```json\n{\"summary\": \"Hej\", \"slide_content\": \"- A\", \"lecturer_additions\": \"- B\", \"key_takeaways\": [\"X\",\"Y\",\"Z\"]}\n```"
        parsed = parse_enrichment_response(raw)

        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["summary"], "Hej")
        self.assertFalse(is_enriched_payload_invalid(parsed))


if __name__ == "__main__":
    unittest.main()
