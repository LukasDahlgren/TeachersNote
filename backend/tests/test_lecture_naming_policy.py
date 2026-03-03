import os
import unittest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

HELPERS_AVAILABLE = True
IMPORT_ERROR: Exception | None = None
try:
    from backend.db import _derive_upload_naming_from_lecture_name, _resolve_backfilled_upload_raw_fields
    from backend.main import (
        ApproveLectureRequest,
        _build_standard_stem,
        _normalize_upload_naming_fields,
        _raw_upload_naming_fields,
    )
except Exception as exc:
    IMPORT_ERROR = exc
    HELPERS_AVAILABLE = False
    ApproveLectureRequest = None  # type: ignore[assignment]
    _build_standard_stem = None  # type: ignore[assignment]
    _derive_upload_naming_from_lecture_name = None  # type: ignore[assignment]
    _normalize_upload_naming_fields = None  # type: ignore[assignment]
    _raw_upload_naming_fields = None  # type: ignore[assignment]
    _resolve_backfilled_upload_raw_fields = None  # type: ignore[assignment]


@unittest.skipUnless(HELPERS_AVAILABLE, f"naming helpers unavailable: {IMPORT_ERROR}")
class LectureNamingPolicyTests(unittest.TestCase):
    def test_approve_request_requires_all_fields(self) -> None:
        with self.assertRaises(Exception) as ctx:
            ApproveLectureRequest()
        self.assertIn("ValidationError", type(ctx.exception).__name__)

    def test_strict_approval_rejects_kind_outside_lecture_or_other(self) -> None:
        with self.assertRaises(Exception) as ctx:
            _normalize_upload_naming_fields(
                "IB130N",
                "seminar",
                "3",
                "2026",
                strict_kind=True,
            )
        self.assertEqual(getattr(ctx.exception, "status_code", None), 400)
        self.assertIn("lecture, other", str(getattr(ctx.exception, "detail", "")))

    def test_upload_flow_maps_unknown_kind_to_other(self) -> None:
        courseid, kind, lecture, year = _normalize_upload_naming_fields(
            " ib130n ",
            "seminar",
            "lecture 3",
            "2026",
        )
        self.assertEqual(courseid, "IB130N")
        self.assertEqual(kind, "other")
        self.assertEqual(lecture, "lecture-3")
        self.assertEqual(year, "2026")

    def test_raw_input_is_preserved_when_kind_is_mapped(self) -> None:
        raw = _raw_upload_naming_fields(" IB130N ", " Seminar ", " L3 ", " 2026 ")
        _, kind, _, _ = _normalize_upload_naming_fields(
            raw.courseid or "",
            raw.kind or "",
            raw.lecture or "",
            raw.year or "",
        )
        self.assertEqual(raw.kind, "Seminar")
        self.assertEqual(kind, "other")

    def test_standard_stem_rebuilt_from_normalized_parts(self) -> None:
        normalized = _normalize_upload_naming_fields(
            "ib130n",
            "other",
            "lecture 3",
            "2026",
            strict_kind=True,
        )
        self.assertEqual(_build_standard_stem(*normalized), "IB130N-other-lecture-3-2026")


@unittest.skipUnless(HELPERS_AVAILABLE, f"naming helpers unavailable: {IMPORT_ERROR}")
class LectureNamingBackfillTests(unittest.TestCase):
    def test_backfill_prefers_existing_then_canonical_then_parsed(self) -> None:
        values = _resolve_backfilled_upload_raw_fields(
            lecture_name="IB130N-lecture-3-2026",
            canonical_courseid="IB130N",
            canonical_kind="lecture",
            canonical_lecture="3",
            canonical_year="2026",
            existing_raw_courseid=None,
            existing_raw_kind="Seminar",
            existing_raw_lecture=None,
            existing_raw_year=None,
        )
        self.assertEqual(
            values,
            ("IB130N", "Seminar", "3", "2026"),
        )

    def test_backfill_uses_parsed_name_when_canonical_missing(self) -> None:
        values = _resolve_backfilled_upload_raw_fields(
            lecture_name="IB200N-seminar-topic-2025",
            canonical_courseid=None,
            canonical_kind=None,
            canonical_lecture=None,
            canonical_year=None,
            existing_raw_courseid=None,
            existing_raw_kind=None,
            existing_raw_lecture=None,
            existing_raw_year=None,
        )
        self.assertEqual(values, ("IB200N", "seminar", "topic", "2025"))

    def test_backfill_keeps_null_when_name_not_derivable(self) -> None:
        parsed = _derive_upload_naming_from_lecture_name("untitled upload")
        self.assertEqual(parsed, (None, None, None, None))


if __name__ == "__main__":
    unittest.main()
