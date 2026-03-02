import unittest
from datetime import date
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
