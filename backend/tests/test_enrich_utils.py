import unittest

from scripts.enrich import (
    enforce_relevance_policy,
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


class RelevancePolicyTests(unittest.TestCase):
    def test_removes_operational_chatter_from_all_fields(self) -> None:
        payload = {
            "summary": "Vi justerar kameran innan vi forklarar derivata.",
            "slide_content": "- Derivata beskriver lutning\n- Vi fixar mikrofonen nu",
            "lecturer_additions": "- Vi justerar kameran\n- Lutningen blir storre nar x okar",
            "key_takeaways": [
                "Kontrollera ljudet i salen",
                "Derivata beskriver forandringshastighet",
                "Justera zoom innan vi fortsatter",
            ],
        }
        filtered = enforce_relevance_policy(payload, "Derivata och lutning i en funktion")

        all_text = " ".join([
            filtered["summary"],
            filtered["slide_content"],
            filtered["lecturer_additions"],
            " ".join(filtered["key_takeaways"]),
        ]).lower()
        self.assertNotIn("kamera", all_text)
        self.assertNotIn("mikrofon", all_text)
        self.assertNotIn("zoom", all_text)
        self.assertNotIn("ljud", all_text)

    def test_keeps_slide_relevant_points_when_mixed_with_off_topic(self) -> None:
        payload = {
            "summary": "Gradient descent minskar forlusten stegvis.",
            "slide_content": "- Uppdatering sker med learning rate\n- Vi tar paus snart",
            "lecturer_additions": "- Metoden kravet val av learning rate\n- Jag oppnar chatten nu",
            "key_takeaways": [
                "Learning rate styr steglangden",
                "Vi tar rast nu",
                "Gradient pekar mot minskad forlust",
            ],
        }
        filtered = enforce_relevance_policy(
            payload,
            "Gradient descent minimerar forlustfunktionen med learning rate",
        )

        self.assertIn("gradient descent", filtered["summary"].lower())
        self.assertIn("forlust", filtered["summary"].lower())
        self.assertIn("learning rate", filtered["slide_content"].lower())
        self.assertNotIn("paus", filtered["slide_content"].lower())
        self.assertNotIn("chatten", filtered["lecturer_additions"].lower())
        self.assertTrue(any("learning rate" in t.lower() for t in filtered["key_takeaways"]))

    def test_summary_is_recovered_when_original_summary_is_removed(self) -> None:
        payload = {
            "summary": "Vi justerar kameran innan vi borjar.",
            "slide_content": "- GROUP BY grupperar rader\n- COUNT raknar antal i varje grupp",
            "lecturer_additions": "- Mikrofonen brusar nu",
            "key_takeaways": ["GROUP BY och COUNT visar statistik per avdelning"],
        }
        filtered = enforce_relevance_policy(payload, "GROUP BY och COUNT per avdelning")

        self.assertTrue(filtered["summary"].strip())
        self.assertNotIn("kamera", filtered["summary"].lower())
        self.assertFalse(is_enriched_payload_invalid(filtered))

    def test_enforces_section_floors_for_slide_content_and_takeaways(self) -> None:
        payload = {
            "summary": "Introduktion till normalisering.",
            "slide_content": "- 1NF tar bort upprepade grupper",
            "lecturer_additions": "- Vi tar paus snart",
            "key_takeaways": ["1NF strukturerar data"],
        }
        filtered = enforce_relevance_policy(payload, "Normalisering: 1NF 2NF 3NF och funktionella beroenden")

        slide_bullets = [line for line in filtered["slide_content"].splitlines() if line.strip()]
        self.assertGreaterEqual(len(slide_bullets), 2)
        self.assertLessEqual(len(slide_bullets), 4)
        self.assertGreaterEqual(len(filtered["key_takeaways"]), 2)
        self.assertLessEqual(len(filtered["key_takeaways"]), 4)
        self.assertFalse(any("paus" in line.lower() for line in slide_bullets))

    def test_lecturer_additions_caps_academic_misc_points(self) -> None:
        payload = {
            "summary": "Backpropagation anvander kedjeregeln.",
            "slide_content": "- Kedjeregeln gor gradientberakning mojlig",
            "lecturer_additions": (
                "- Kedjeregeln behovs i backpropagation\n"
                "- Det har kommer pa tentan\n"
                "- Labb 2 tranar samma metod"
            ),
            "key_takeaways": ["Backpropagation bygger pa kedjeregeln"],
        }
        filtered = enforce_relevance_policy(payload, "Backpropagation och kedjeregeln")

        lines = [line.strip() for line in filtered["lecturer_additions"].splitlines() if line.strip()]
        misc_count = sum("tenta" in line.lower() or "labb" in line.lower() for line in lines)
        self.assertLessEqual(misc_count, 3)
        self.assertTrue(any("kedjeregeln" in line.lower() for line in lines))

    def test_takeaways_remain_valid_list_after_filtering(self) -> None:
        payload = {
            "summary": "Standardavvikelse visar spridning i normalfordelningen.",
            "slide_content": "- Standardavvikelse mater spridning",
            "lecturer_additions": "- Vi byter HDMI-kabel",
            "key_takeaways": [
                "Kameran ar sned",
                "Mikrofonen brusar",
                "Vi tar fem minuters paus",
            ],
        }
        filtered = enforce_relevance_policy(payload, "Normalfordelning och standardavvikelse")

        self.assertIsInstance(filtered["key_takeaways"], list)
        self.assertGreater(len(filtered["key_takeaways"]), 0)
        self.assertLessEqual(len(filtered["key_takeaways"]), 4)
        self.assertFalse(is_enriched_payload_invalid(filtered))

    def test_length_guardrail_restores_depth_with_moderate_candidates(self) -> None:
        payload = {
            "summary": "Views forenklar SQL och skapar logiskt dataoberoende.",
            "slide_content": "- Views kapslar in komplexa SELECT-satser",
            "lecturer_additions": (
                "- Views minskar duplicerad SQL-kod i stora projekt\n"
                "- Views skyddar anvandare fran underliggande tabellforandringar\n"
                "- Views gor rapportering med aggregering tydligare\n"
                "- Vi justerar kameran\n"
                "- Views ar anvandbara med COUNT och GROUP BY"
            ),
            "key_takeaways": [
                "Views kan ateranvandas for att undvika kodupprepning",
                "Logiskt dataoberoende underlattar underhall",
            ],
        }
        filtered = enforce_relevance_policy(payload, "Views, logiskt dataoberoende, SQL-ateranvandning och aggregering")

        lecturer_bullets = [line for line in filtered["lecturer_additions"].splitlines() if line.strip()]
        self.assertGreaterEqual(len(lecturer_bullets), 4)
        self.assertNotIn("kamera", filtered["lecturer_additions"].lower())
        self.assertFalse(is_enriched_payload_invalid(filtered))

    def test_preserves_markdown_bold_markers_in_relevant_output(self) -> None:
        payload = {
            "summary": "SQL använder **GROUP BY** för att gruppera data.",
            "slide_content": "- **GROUP BY** grupperar rader\n- **COUNT** raknar poster",
            "lecturer_additions": "- **HAVING** filtrerar grupper efter aggregering",
            "key_takeaways": [
                "**GROUP BY** ar central for aggregering",
                "**COUNT** ger antal per grupp",
                "**HAVING** filtrerar efter aggregate-villkor",
            ],
        }
        filtered = enforce_relevance_policy(payload, "GROUP BY COUNT HAVING i SQL")

        combined = " ".join([
            filtered["summary"],
            filtered["slide_content"],
            filtered["lecturer_additions"],
            " ".join(filtered["key_takeaways"]),
        ])
        self.assertIn("**GROUP BY**", combined)
        self.assertIn("**COUNT**", combined)


if __name__ == "__main__":
    unittest.main()
