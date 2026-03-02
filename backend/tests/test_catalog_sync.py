import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    import catalog_sync as catalog_sync_module
except ModuleNotFoundError:
    import backend.catalog_sync as catalog_sync_module



class CatalogSyncNormalizationTests(unittest.TestCase):
    def test_normalize_standalone_filters_non_dsv_and_missing_required(self) -> None:
        warnings: list[str] = []
        rows = [
            SimpleNamespace(
                snapshot_date="2026-03-01",
                course_code="IB130N",
                course_name_sv="Introduktion",
                level="Grundnivå",
                catalog_url="https://www.su.se/utbildning/utbildningskatalog/ib/ib130n",
                institution_name="Institutionen för data- och systemvetenskap",
            ),
            SimpleNamespace(
                snapshot_date="2026-03-01",
                course_code="IB131N",
                course_name_sv="IT i organisationer",
                level="Grundnivå",
                catalog_url="",
                institution_name="Institutionen för data- och systemvetenskap",
            ),
            SimpleNamespace(
                snapshot_date="2026-03-01",
                course_code="IB132N",
                course_name_sv="Objektorienterad analys och design",
                level="Grundnivå",
                catalog_url="https://www.su.se/utbildning/utbildningskatalog/ib/ib132n",
                institution_name="Någon annan institution",
            ),
        ]

        normalized = catalog_sync_module.normalize_standalone_courses(rows, warnings)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].course_code, "IB130N")
        self.assertGreaterEqual(len(warnings), 2)


class CatalogSyncDiffTests(unittest.TestCase):
    def test_compute_catalog_change_plan_detects_upserts_and_deactivations(self) -> None:
        existing_programs = {
            "SAFFK": SimpleNamespace(name="Old Name", is_active=True),
            "SOLDX": SimpleNamespace(name="Legacy Program", is_active=True),
        }
        incoming_programs = {
            "SAFFK": catalog_sync_module.ProgramInfo(
                snapshot_date="2026-03-01",
                program_code="SAFFK",
                program_name_sv="New Name",
                level="Grundnivå",
                catalog_url="https://example.test/program/saffk",
                institution_name="Institutionen för data- och systemvetenskap",
            ),
            "SNEWP": catalog_sync_module.ProgramInfo(
                snapshot_date="2026-03-01",
                program_code="SNEWP",
                program_name_sv="Brand New Program",
                level="Avancerad nivå",
                catalog_url="https://example.test/program/snewp",
                institution_name="Institutionen för data- och systemvetenskap",
            ),
        }

        existing_courses = {
            "IB130N": SimpleNamespace(name="Old Intro", is_active=True),
            "IB999N": SimpleNamespace(name="Legacy", is_active=True),
        }
        incoming_courses = {
            "IB130N": "Introduktion till data- och systemvetenskap",
            "IB131N": "IT i organisationer",
        }

        plan = catalog_sync_module.compute_catalog_change_plan(
            existing_programs=existing_programs,
            incoming_programs=incoming_programs,
            existing_courses=existing_courses,
            incoming_courses=incoming_courses,
        )

        self.assertEqual(plan.programs_created_codes, {"SNEWP"})
        self.assertEqual(plan.programs_updated_codes, {"SAFFK"})
        self.assertEqual(plan.programs_deactivated_codes, {"SOLDX"})
        self.assertEqual(plan.courses_created_codes, {"IB131N"})
        self.assertEqual(plan.courses_updated_codes, {"IB130N"})
        self.assertEqual(plan.courses_deactivated_codes, {"IB999N"})

    def test_compute_mapping_deltas_replaces_stale_pairs(self) -> None:
        existing = {
            ("SAFFK", "IB130N"),
            ("SAFFK", "IB132N"),
        }
        target = {
            ("SAFFK", "IB130N"),
            ("SAFFK", "IB131N"),
        }

        to_add, to_remove = catalog_sync_module.compute_mapping_deltas(existing, target)

        self.assertEqual(to_add, {("SAFFK", "IB131N")})
        self.assertEqual(to_remove, {("SAFFK", "IB132N")})


class ProgramPlanPayloadTests(unittest.TestCase):
    def test_build_program_plan_payloads_shapes_rows_and_order(self) -> None:
        rows = [
            catalog_sync_module.ProgramCourseEntry(
                snapshot_date="2026-03-01",
                program_code="SAFFK",
                program_name_sv="Program A",
                term_label="Termin 1",
                group_type="mandatory",
                group_label="Core",
                course_code="IB130N",
                course_name_sv="Introduktion",
                course_url="https://example.test/course/ib130n",
            ),
            catalog_sync_module.ProgramCourseEntry(
                snapshot_date="2026-03-01",
                program_code="SAFFK",
                program_name_sv="Program A",
                term_label="Termin 1",
                group_type="optional",
                group_label="Electives",
                course_code=None,
                course_name_sv="Valbar kurs",
                course_url="https://example.test/course/elective",
            ),
        ]

        payloads = catalog_sync_module.build_program_plan_payloads(
            rows,
            program_id_by_code={"SAFFK": 7},
            course_id_by_code={"IB130N": 42},
            snapshot_day=date(2026, 3, 1),
        )

        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["display_order"], 1)
        self.assertEqual(payloads[1]["display_order"], 2)
        self.assertEqual(payloads[0]["course_id"], 42)
        self.assertIsNone(payloads[1]["course_id"])
        self.assertEqual(payloads[1]["group_type"], "optional")


class DryRunStateTests(unittest.TestCase):
    def test_apply_code_updates_dry_run_does_not_mutate_input(self) -> None:
        existing = {
            "SAFFK": {"name": "Program A", "is_active": True},
            "SOLDX": {"name": "Legacy", "is_active": True},
        }
        incoming = {
            "SAFFK": "Program A Updated",
            "SNEWP": "Program B",
        }

        dry_result = catalog_sync_module.apply_code_updates(existing, incoming, dry_run=True)

        self.assertEqual(existing["SAFFK"]["name"], "Program A")
        self.assertTrue(existing["SOLDX"]["is_active"])
        self.assertEqual(dry_result["SAFFK"]["name"], "Program A")
        self.assertTrue(dry_result["SOLDX"]["is_active"])

        apply_result = catalog_sync_module.apply_code_updates(existing, incoming, dry_run=False)
        self.assertEqual(apply_result["SAFFK"]["name"], "Program A Updated")
        self.assertTrue(apply_result["SNEWP"]["is_active"])
        self.assertFalse(apply_result["SOLDX"]["is_active"])


class _QueryResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeAsyncSession:
    def __init__(self, *, programs, courses, mappings):
        self._programs = list(programs)
        self._courses = list(courses)
        self._mappings = list(mappings)
        self.add_calls = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self.executed_sql = []

    async def execute(self, statement):
        sql = str(statement).lower()
        self.executed_sql.append(sql)
        if "from program_courses" in sql:
            return _QueryResult(self._mappings)
        if "from programs" in sql:
            return _QueryResult(self._programs)
        if "from courses" in sql:
            return _QueryResult(self._courses)
        return _QueryResult([])

    def add(self, obj):
        self.add_calls.append(obj)

    async def flush(self):
        self.flush_calls += 1

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        self.rollback_calls += 1


class RunCatalogSyncDryRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_catalog_sync_dry_run_does_not_mutate_db_session(self) -> None:
        try:
            import sqlalchemy  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("sqlalchemy is not installed in this test environment.")

        standalone_rows = [
            catalog_sync_module.StandaloneCourse(
                snapshot_date="2026-03-01",
                course_code="IB130N",
                course_name_sv="Introduktion",
                level="Grundnivå",
                catalog_url="https://example.test/ib130n",
                institution_name="Institutionen för data- och systemvetenskap",
            )
        ]
        program_rows = [
            catalog_sync_module.ProgramInfo(
                snapshot_date="2026-03-01",
                program_code="SAFFK",
                program_name_sv="Program A",
                level="Grundnivå",
                catalog_url="https://example.test/saffk",
                institution_name="Institutionen för data- och systemvetenskap",
            )
        ]
        program_course_rows = [
            catalog_sync_module.ProgramCourseEntry(
                snapshot_date="2026-03-01",
                program_code="SAFFK",
                program_name_sv="Program A",
                term_label="Termin 1",
                group_type="mandatory",
                group_label="Core",
                course_code="IB130N",
                course_name_sv="Introduktion",
                course_url="https://example.test/ib130n",
            )
        ]
        fake_db = _FakeAsyncSession(
            programs=[SimpleNamespace(code="SOLDX", name="Legacy program", is_active=True)],
            courses=[SimpleNamespace(code="IB999N", name="Legacy course", is_active=True)],
            mappings=[("SOLDX", "IB999N")],
        )

        with patch.object(
            catalog_sync_module.asyncio,
            "to_thread",
            new=AsyncMock(return_value=(standalone_rows, program_rows, program_course_rows, ["warning"])),
        ):
            result = await catalog_sync_module.run_catalog_sync(
                fake_db,
                snapshot_date=date(2026, 3, 1),
                dry_run=True,
                write_snapshot_files_to_disk=False,
            )

        self.assertTrue(result.dry_run)
        self.assertEqual(result.snapshot_date, "2026-03-01")
        self.assertEqual(result.programs_created, 1)
        self.assertEqual(result.programs_deactivated, 1)
        self.assertEqual(result.courses_created, 1)
        self.assertEqual(result.courses_deactivated, 1)
        self.assertEqual(result.mappings_added, 1)
        self.assertEqual(result.mappings_removed, 1)
        self.assertEqual(result.program_plan_rows_written, 1)
        self.assertEqual(result.warnings, ["warning"])
        self.assertEqual(fake_db.add_calls, [])
        self.assertEqual(fake_db.flush_calls, 0)
        self.assertEqual(fake_db.commit_calls, 0)


if __name__ == "__main__":
    unittest.main()
