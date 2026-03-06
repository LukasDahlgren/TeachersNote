import unittest

STORE_IMPORT_ERROR: Exception | None = None
try:
    from backend.jobs.regeneration_jobs import RegenerationJobStore
    from backend.jobs.upload_jobs import HTTPException, UploadJobStore
except Exception as exc:
    HTTPException = Exception  # type: ignore[assignment]
    RegenerationJobStore = None  # type: ignore[assignment]
    UploadJobStore = None  # type: ignore[assignment]
    STORE_IMPORT_ERROR = exc


@unittest.skipIf(
    UploadJobStore is None or RegenerationJobStore is None,
    f"job store modules unavailable in this environment: {STORE_IMPORT_ERROR}",
)
class UploadJobStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_update_and_event_sequence(self) -> None:
        store = UploadJobStore(ttl_seconds=60)
        created = await store.create_job("alice")
        self.assertEqual(created["status"], "queued")

        updated = await store.update_job(
            created["job_id"],
            status="running",
            current_stage="transcribe",
            progress_pct=135,
            lecture_id=42,
            event_name="progress",
            message="Working",
        )
        self.assertIsNotNone(updated)
        snapshot, events = await store.get_job_snapshot_and_events(created["job_id"], after_event_id=0)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["lecture_id"], 42)
        self.assertEqual(snapshot["progress_pct"], 100)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "progress")
        self.assertEqual(events[0]["payload"]["event_id"], 1)
        self.assertEqual(events[0]["payload"]["message"], "Working")

    async def test_terminal_update_clears_active_job(self) -> None:
        store = UploadJobStore(ttl_seconds=60)
        created = await store.create_job("alice")
        self.assertIsNotNone(await store.get_active_job("alice"))

        await store.update_job(created["job_id"], status="done")
        self.assertIsNone(await store.get_active_job("alice"))

    async def test_cleanup_removes_expired_terminal_jobs_only(self) -> None:
        store = UploadJobStore(ttl_seconds=10)
        done_job = await store.create_job("alice")
        running_job = await store.create_job("bob")
        await store.update_job(done_job["job_id"], status="done")
        running_before = await store.get_job_snapshot(running_job["job_id"])
        done_before = await store.get_job_snapshot(done_job["job_id"])
        self.assertIsNotNone(running_before)
        self.assertIsNotNone(done_before)

        await store.cleanup_expired_jobs(now=float(done_before["updated_at"]) + 20)

        self.assertIsNone(await store.get_job_snapshot(done_job["job_id"]))
        self.assertIsNotNone(await store.get_job_snapshot(running_job["job_id"]))

    async def test_owner_check_raises_hidden_404(self) -> None:
        store = UploadJobStore(ttl_seconds=60)
        created = await store.create_job("alice")

        with self.assertRaises(HTTPException) as ctx:
            store.assert_user_can_view_job(user_id="bob", job=created)

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_raw_events_increment_event_ids_and_filtering(self) -> None:
        store = UploadJobStore(ttl_seconds=60)
        created = await store.create_job("alice")

        await store.add_raw_event(created["job_id"], "slide_enriched", {"slide": 1})
        await store.add_raw_event(created["job_id"], "slide_enriched", {"slide": 2})

        _, events = await store.get_job_snapshot_and_events(created["job_id"], after_event_id=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["slide"], 2)
        self.assertEqual(events[0]["payload"]["event_id"], 2)


@unittest.skipIf(
    UploadJobStore is None or RegenerationJobStore is None,
    f"job store modules unavailable in this environment: {STORE_IMPORT_ERROR}",
)
class RegenerationJobStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_update_and_public_state(self) -> None:
        store = RegenerationJobStore(ttl_seconds=60)
        created = await store.create_job(lecture_id=5, total_slides=3)
        updated = await store.update_job(
            created["job_id"],
            status="running",
            completed_slides=1,
            current_slide=2,
            regenerated_slides=1,
        )
        self.assertIsNotNone(updated)
        public = store.public_state(updated)
        self.assertEqual(public["lecture_id"], 5)
        self.assertEqual(public["completed_slides"], 1)
        self.assertEqual(public["current_slide"], 2)
        self.assertIn("+00:00", public["updated_at"])

    async def test_active_job_lookup_clears_on_terminal_status(self) -> None:
        store = RegenerationJobStore(ttl_seconds=60)
        created = await store.create_job(lecture_id=5, total_slides=3)
        self.assertIsNotNone(await store.get_active_job_for_lecture(5))

        await store.update_job(created["job_id"], status="error", error="boom")
        self.assertIsNone(await store.get_active_job_for_lecture(5))

    async def test_cleanup_removes_expired_terminal_jobs_only(self) -> None:
        store = RegenerationJobStore(ttl_seconds=10)
        done_job = await store.create_job(lecture_id=1, total_slides=1)
        running_job = await store.create_job(lecture_id=2, total_slides=2)
        await store.update_job(done_job["job_id"], status="done")
        done_before = await store.get_job_snapshot(done_job["job_id"])
        self.assertIsNotNone(done_before)

        await store.cleanup_expired_jobs(now=float(done_before["updated_at"]) + 20)

        self.assertIsNone(await store.get_job_snapshot(done_job["job_id"]))
        self.assertIsNotNone(await store.get_job_snapshot(running_job["job_id"]))


if __name__ == "__main__":
    unittest.main()
