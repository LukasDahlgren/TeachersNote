import json
import unittest
from unittest.mock import patch

from scripts.enrich import (
    build_fallback_enrichment,
    enrich_slides_batch_with_retry,
    build_user_prompt,
    enforce_relevance_policy,
    is_enriched_payload_invalid,
    normalize_enriched_payload,
    parse_enrichment_batch_response,
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

    def test_build_user_prompt_normalizes_wrapped_slide_lines(self) -> None:
        slide = {
            "slide": 7,
            "text": (
                "Korrelation - Mapping\n"
                "Relationen mellan det jag\n"
                "styr/kontrollerar med och det som\n"
                "styrs/kontrolleras"
            ),
        }

        prompt = build_user_prompt(slide, "Kort transkript.")

        self.assertIn(
            "Relationen mellan det jag styr/kontrollerar med och det som styrs/kontrolleras",
            prompt,
        )
        self.assertNotIn("Relationen mellan det jag\nstyr/kontrollerar", prompt)

    def test_fallback_uses_normalized_slide_text_and_empty_lecturer_notes_without_transcript(self) -> None:
        slide = {
            "slide": 7,
            "text": (
                "Korrelation - Mapping\n"
                "Relationen mellan det jag\n"
                "styr/kontrollerar med och det som\n"
                "styrs/kontrolleras"
            ),
        }

        fallback = build_fallback_enrichment(slide, "")

        self.assertIn(
            "Relationen mellan det jag styr/kontrollerar med och det som styrs/kontrolleras",
            fallback["slide_content"],
        )
        self.assertEqual(fallback["lecturer_additions"], "")


class EnrichmentBatchTests(unittest.TestCase):
    def test_parse_batch_json_response_with_surrounding_text(self) -> None:
        raw = (
            "Svar:\n```json\n"
            "["
            "{\"slide\": 1, \"summary\": \"S1\", \"slide_content\": \"- A\", \"lecturer_additions\": \"\", \"key_takeaways\": [\"X\", \"Y\"]},"
            "{\"slide\": 2, \"summary\": \"S2\", \"slide_content\": \"- B\", \"lecturer_additions\": \"\", \"key_takeaways\": [\"Z\", \"W\"]}"
            "]\n```"
        )

        parsed = parse_enrichment_batch_response(raw)

        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed or []), 2)
        self.assertEqual(parsed[1]["slide"], 2)

    def test_batch_helper_recovers_missing_slide_individually(self) -> None:
        slides_with_transcripts = [
            (
                {"slide": 1, "text": "Derivata och lutning i funktioner"},
                "Derivata beskriver hur lutningen i kurvan andras.",
            ),
            (
                {"slide": 2, "text": "Gradient descent och learning rate"},
                "Learning rate styr hur stora steg optimeringen tar.",
            ),
        ]
        batch_raw = json.dumps(
            [
                {
                    "slide": 1,
                    "summary": "Derivata forklarar hur lutningen i en funktion beraknas.",
                    "slide_content": (
                        "- **Derivata** anger funktionens lokala lutning\n"
                        "- **Lutning** visar hur snabbt vardet andras"
                    ),
                    "lecturer_additions": "",
                    "key_takeaways": [
                        "**Derivata** beskriver lokal forandring i funktionen",
                        "**Lutning** kan vara positiv eller negativ i grafen",
                    ],
                }
            ],
            ensure_ascii=False,
        )

        with (
            patch(
                "scripts.enrich._call_enrichment_model",
                return_value=(batch_raw, {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}),
            ),
            patch(
                "scripts.enrich.enrich_slide_with_retry",
                return_value=(
                    {
                        "summary": "Gradient descent styr optimeringen med learning rate.",
                        "slide_content": (
                            "- **Gradient descent** minskar forlusten stegvis\n"
                            "- **Learning rate** bestammer steglangden i uppdateringen"
                        ),
                        "lecturer_additions": "",
                        "key_takeaways": [
                            "**Gradient descent** minimerar forlustfunktionen stegvis",
                            "**Learning rate** avgor hur stora uppdateringar modellen gor",
                        ],
                    },
                    {
                        "attempts": 1,
                        "retries": 1,
                        "fallback_used": False,
                        "duration_ms": 12,
                        "input_tokens": 5,
                        "output_tokens": 3,
                        "total_tokens": 8,
                        "raw_transcript_words": 8,
                        "prompt_transcript_words": 8,
                        "failure_reason": "none",
                    },
                ),
            ) as single_mock,
        ):
            results, metrics = enrich_slides_batch_with_retry(
                object(),
                slides_with_transcripts,
                provider="anthropic",
                model="fake-model",
                max_attempts=2,
                log_usage=False,
            )

        self.assertEqual([entry["slide"] for entry in results], [1, 2])
        self.assertEqual(single_mock.call_count, 1)
        self.assertEqual(single_mock.call_args.args[1]["slide"], 2)
        self.assertEqual(metrics["input_tokens"], 16)
        self.assertEqual(metrics["output_tokens"], 10)
        self.assertEqual(metrics["total_tokens"], 26)
        self.assertEqual(metrics["retries"], 1)
        self.assertEqual(metrics["fallbacks"], 0)

    def test_batch_helper_retries_then_recovers_slides_individually(self) -> None:
        slides_with_transcripts = [
            (
                {"slide": 3, "text": "SQL joins och tabellrelationer"},
                "Joins kombinerar rader mellan relaterade tabeller.",
            ),
            (
                {"slide": 4, "text": "GROUP BY och COUNT i SQL"},
                "GROUP BY grupperar rader och COUNT summerar antal.",
            ),
        ]
        single_results = [
            (
                {
                    "summary": "Joins kombinerar data fran relaterade tabeller.",
                    "slide_content": (
                        "- **Joins** kopplar samman relaterade tabeller\n"
                        "- **Relationer** gor att matchande rader kan kombineras"
                    ),
                    "lecturer_additions": "",
                    "key_takeaways": [
                        "**Joins** bygger pa matchande nycklar mellan tabeller",
                        "**Relationer** avgor vilka rader som ska kombineras",
                    ],
                },
                {
                    "attempts": 1,
                    "retries": 0,
                    "fallback_used": True,
                    "duration_ms": 7,
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                    "raw_transcript_words": 6,
                    "prompt_transcript_words": 6,
                    "failure_reason": "connection_error",
                },
            ),
            (
                {
                    "summary": "GROUP BY och COUNT sammanfattar data per grupp.",
                    "slide_content": (
                        "- **GROUP BY** grupperar rader efter vald kolumn\n"
                        "- **COUNT** raknar antal poster i varje grupp"
                    ),
                    "lecturer_additions": "",
                    "key_takeaways": [
                        "**GROUP BY** delar upp data i tydliga grupper",
                        "**COUNT** visar antal poster for varje grupp",
                    ],
                },
                {
                    "attempts": 1,
                    "retries": 0,
                    "fallback_used": False,
                    "duration_ms": 6,
                    "input_tokens": 4,
                    "output_tokens": 2,
                    "total_tokens": 6,
                    "raw_transcript_words": 7,
                    "prompt_transcript_words": 7,
                    "failure_reason": "none",
                },
            ),
        ]

        with (
            patch(
                "scripts.enrich._call_enrichment_model",
                return_value=("not json", {"input_tokens": 9, "output_tokens": 0, "total_tokens": 9}),
            ) as call_mock,
            patch("scripts.enrich.time.sleep"),
            patch(
                "scripts.enrich.enrich_slide_with_retry",
                side_effect=single_results,
            ) as single_mock,
        ):
            results, metrics = enrich_slides_batch_with_retry(
                object(),
                slides_with_transcripts,
                provider="anthropic",
                model="fake-model",
                max_attempts=2,
                log_usage=False,
            )

        self.assertEqual(call_mock.call_count, 2)
        self.assertEqual(single_mock.call_count, 2)
        self.assertEqual([entry["slide"] for entry in results], [3, 4])
        self.assertEqual(metrics["retries"], 1)
        self.assertEqual(metrics["fallbacks"], 1)
        self.assertEqual(metrics["failure_reason_counts"]["connection_error"], 1)


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

    def test_wrapped_slide_sentence_is_removed_from_lecturer_notes(self) -> None:
        slide_text = (
            "Korrelation - Mapping\n"
            "Relationen mellan det jag\n"
            "styr/kontrollerar med och det som\n"
            "styrs/kontrolleras"
        )
        payload = {
            "summary": "Mapping beskriver kopplingen mellan kontroll och systemrespons.",
            "slide_content": "- Mapping visar relationen mellan kontroll och systemrespons",
            "lecturer_additions": (
                "Relationen mellan det jag\n"
                "styr/kontrollerar med och det som\n"
                "styrs/kontrolleras\n"
                "- Exempel: Forelasaren anvande segelbaten for att visa hur fel mapping kanns"
            ),
            "key_takeaways": [
                "Naturlig mapping foljer anvandarens forvantningar",
                "Fel mapping skapar forvirring",
            ],
        }

        filtered = enforce_relevance_policy(payload, slide_text)

        self.assertNotIn("Relationen mellan det jag", filtered["lecturer_additions"])
        self.assertIn("segelbaten", filtered["lecturer_additions"].lower())

    def test_keeps_spoken_elaboration_that_adds_beyond_slide_text(self) -> None:
        payload = {
            "summary": "Natural mapping gor styrning intuitiv.",
            "slide_content": "- Mapping beskriver relationen mellan kontroll och respons",
            "lecturer_additions": (
                "- Forelasaren betonade att mapping ar ett designval som avgor om ett granssnitt kanns intuitivt eller forvirrande"
            ),
            "key_takeaways": [
                "Natural mapping minskar forvirring",
                "Design bor folja anvandarens forvantningar",
            ],
        }

        filtered = enforce_relevance_policy(
            payload,
            "Korrelation - Mapping\nRelationen mellan kontroll och respons",
        )

        self.assertIn("designval", filtered["lecturer_additions"].lower())
        self.assertIn("intuitivt", filtered["lecturer_additions"].lower())

    def test_removes_copied_slide_text_from_lecturer_notes_and_allows_empty_result(self) -> None:
        payload = {
            "summary": "Mapping forklarar relationen mellan kontroll och respons.",
            "slide_content": "- Mapping forklarar relationen mellan kontroll och respons",
            "lecturer_additions": "- Mapping forklarar relationen mellan kontroll och respons",
            "key_takeaways": [
                "God mapping gor systemet enklare att forsta",
                "Kontroller bor matcha anvandarens forvantningar",
            ],
        }

        filtered = enforce_relevance_policy(
            payload,
            "Mapping forklarar relationen mellan kontroll och respons",
        )

        self.assertEqual(filtered["lecturer_additions"], "")

    def test_takeaways_remain_valid_list_after_filtering(self) -> None:
        payload = {
            "summary": "Standardavvikelse visar spridning i normalfordelningen.",
            "slide_content": "- Standardavvikelse mater spridning i datamangden",
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
