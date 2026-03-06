import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

STORE_IMPORT_ERROR: Exception | None = None
try:
    from backend.services.serializers import (
        _archive_response_payload,
        _course_payload,
        _lecture_naming_snapshot,
        _profile_payload,
        _program_course_plan_payload,
        _program_payload,
        _resolve_course_display,
        _teachers_note_payload,
        lecture_to_response,
    )
except Exception as exc:
    _archive_response_payload = None  # type: ignore[assignment]
    _course_payload = None  # type: ignore[assignment]
    _lecture_naming_snapshot = None  # type: ignore[assignment]
    _profile_payload = None  # type: ignore[assignment]
    _program_course_plan_payload = None  # type: ignore[assignment]
    _program_payload = None  # type: ignore[assignment]
    _resolve_course_display = None  # type: ignore[assignment]
    _teachers_note_payload = None  # type: ignore[assignment]
    lecture_to_response = None  # type: ignore[assignment]
    STORE_IMPORT_ERROR = exc


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


class _FakeAsyncSession:
    def __init__(self, rows_per_call):
        self._rows_per_call = list(rows_per_call)
        self._index = 0

    async def execute(self, _statement):
        rows = self._rows_per_call[self._index]
        self._index += 1
        return _ExecuteResult(rows)


@unittest.skipIf(
    lecture_to_response is None,
    f"serializer helpers unavailable in this environment: {STORE_IMPORT_ERROR}",
)
class SerializerTests(unittest.IsolatedAsyncioTestCase):
    def test_summary_payload_builders_preserve_wire_shape(self) -> None:
        now = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
        lecture = SimpleNamespace(
            id=7,
            name="IB133N-lecture-14-2026",
            is_demo=False,
            is_archived=True,
            is_deleted=False,
            is_approved=True,
            course_id="IB133N",
            naming_kind="lecture",
            naming_lecture="14",
            naming_year="2026",
            upload_courseid_raw="ib133n",
            upload_kind_raw="Lecture",
            upload_lecture_raw="14",
            upload_year_raw="2026",
            uploaded_by="alice",
            pptx_path="generated/IB133N-lecture-14-2026.pptx",
            pdf_path="source_pdfs/IB133N-lecture-14-2026.pdf",
            created_at=now,
        )
        program = SimpleNamespace(
            id=3,
            code="PROG1",
            name="Program One",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        course = SimpleNamespace(
            id=4,
            code="IB133N",
            display_code="IB133N",
            name="Algorithms",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        plan_row = SimpleNamespace(
            id=5,
            program_id=3,
            course_id=4,
            term_label="VT26",
            group_type="mandatory",
            group_label="Core",
            course_code="IB133N",
            course_name_sv="Algoritmer",
            course_url="https://example.test/ib133n",
            display_order=2,
            snapshot_date=now.date(),
        )

        teachers_note = _teachers_note_payload(lecture, is_saved=True, course_display="IB133N")
        self.assertEqual(teachers_note["id"], 7)
        self.assertEqual(teachers_note["pdf_url"], "/pdf/IB133N-lecture-14-2026.pdf")
        self.assertTrue(teachers_note["is_saved"])
        self.assertEqual(teachers_note["upload_naming_raw"]["courseid"], "ib133n")

        archive_payload = _archive_response_payload(lecture)
        self.assertTrue(archive_payload["is_archived"])
        self.assertEqual(archive_payload["download_url"], "/download/IB133N-lecture-14-2026.pptx")

        self.assertEqual(_program_payload(program)["code"], "PROG1")
        self.assertEqual(_course_payload(course)["name"], "Algorithms")
        self.assertEqual(_profile_payload(user_id="alice", program=program, selected_courses=[course])["user_id"], "alice")
        self.assertEqual(_program_course_plan_payload(plan_row)["snapshot_date"], "2026-03-06")
        self.assertEqual(
            _lecture_naming_snapshot(lecture),
            ("IB133N", "lecture", "14", "2026"),
        )
        self.assertEqual(
            _resolve_course_display("ib133n", {"IB133N": "IB133N"}),
            "IB133N",
        )

    async def test_lecture_to_response_serializes_rows_in_order(self) -> None:
        db = _FakeAsyncSession([
            [
                SimpleNamespace(slide_number=1, text="Intro"),
                SimpleNamespace(slide_number=2, text="Summary"),
            ],
            [
                SimpleNamespace(start_time=0.0, end_time=2.5, text="hello"),
                SimpleNamespace(start_time=2.5, end_time=5.0, text="world"),
            ],
            [
                SimpleNamespace(slide_number=1, start_segment=0, end_segment=0),
                SimpleNamespace(slide_number=2, start_segment=1, end_segment=1),
            ],
            [
                SimpleNamespace(
                    slide_number=1,
                    summary="Overview",
                    slide_content="- **Intro**",
                    lecturer_additions="",
                    key_takeaways=["A"],
                ),
                SimpleNamespace(
                    slide_number=2,
                    summary="Wrap-up",
                    slide_content="- **Summary**",
                    lecturer_additions="- Extra",
                    key_takeaways=["B"],
                ),
            ],
        ])

        payload = await lecture_to_response(db, 9, include_transcript=False)

        self.assertEqual(
            payload["slides"],
            [{"slide": 1, "text": "Intro"}, {"slide": 2, "text": "Summary"}],
        )
        self.assertEqual(payload["transcript"], [])
        self.assertEqual(
            payload["alignment"],
            [
                {"slide": 1, "start_segment": 0, "end_segment": 0},
                {"slide": 2, "start_segment": 1, "end_segment": 1},
            ],
        )
        self.assertEqual(payload["enhanced"][0]["slide"], 1)
        self.assertEqual(payload["enhanced"][1]["summary"], "Wrap-up")


if __name__ == "__main__":
    unittest.main()
