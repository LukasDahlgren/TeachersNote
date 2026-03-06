import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    from fastapi import HTTPException
except ModuleNotFoundError:  # pragma: no cover - local test env helper
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail


TERMINAL_JOB_STATUSES = frozenset({"done", "error"})


class UploadJobStore:
    def __init__(self, *, ttl_seconds: int, terminal_statuses: set[str] | frozenset[str] = TERMINAL_JOB_STATUSES):
        self.ttl_seconds = ttl_seconds
        self.terminal_statuses = frozenset(terminal_statuses)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active_job_ids: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def public_state(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "current_stage": job["current_stage"],
            "progress_pct": int(job["progress_pct"]),
            "lecture_id": job["lecture_id"],
            "total_slides": job.get("total_slides"),
            "pdf_url": job.get("pdf_url"),
            "reused_existing": bool(job.get("reused_existing")),
            "error": job["error"],
            "updated_at": datetime.fromtimestamp(job["updated_at"], tz=timezone.utc).isoformat(),
        }

    def sse_event(self, event_name: str, payload: dict[str, Any], event_id: int) -> str:
        return f"id: {event_id}\nevent: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def assert_user_can_view_job(self, *, user_id: str, job: dict[str, Any]) -> None:
        if job.get("user_id") == user_id:
            return
        raise HTTPException(status_code=404, detail="Job not found")

    async def cleanup_expired_jobs(self, *, now: float | None = None) -> None:
        current_time = time.time() if now is None else now
        async with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job["status"] in self.terminal_statuses and (current_time - float(job["updated_at"])) > self.ttl_seconds
            ]
            for job_id in expired:
                user_id = self._jobs.get(job_id, {}).get("user_id")
                if user_id and self._active_job_ids.get(user_id) == job_id:
                    self._active_job_ids.pop(user_id, None)
                self._jobs.pop(job_id, None)

    async def get_job_snapshot(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    async def get_active_job(self, user_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job_id = self._active_job_ids.get(user_id)
            if not job_id:
                return None
            job = self._jobs.get(job_id)
            if not job or job["status"] in self.terminal_statuses:
                self._active_job_ids.pop(user_id, None)
                return None
            return dict(job)

    async def create_job(self, user_id: str) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        now = time.time()
        job = {
            "job_id": job_id,
            "user_id": user_id,
            "status": "queued",
            "current_stage": "upload",
            "progress_pct": 0,
            "lecture_id": None,
            "total_slides": None,
            "pdf_url": None,
            "reused_existing": False,
            "error": None,
            "updated_at": now,
            "version": 0,
            "next_event_id": 1,
            "events": [],
        }
        async with self._lock:
            self._jobs[job_id] = job
            self._active_job_ids[user_id] = job_id
        return dict(job)

    async def update_job(
        self,
        job_id: str,
        *,
        event_name: str | None = None,
        message: str | None = None,
        **updates: Any,
    ) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if "progress_pct" in updates:
                updates["progress_pct"] = max(0, min(100, int(updates["progress_pct"])))

            job.update(updates)
            job["updated_at"] = time.time()
            job["version"] = int(job["version"]) + 1

            if event_name:
                event_payload = self.public_state(job)
                if message:
                    event_payload["message"] = message

                event_id = int(job["next_event_id"])
                job["next_event_id"] = event_id + 1
                event_payload["event_id"] = event_id
                job["events"].append({
                    "id": event_id,
                    "event": event_name,
                    "payload": event_payload,
                })
                if len(job["events"]) > 2000:
                    job["events"] = job["events"][-1000:]

            if job["status"] in self.terminal_statuses:
                user_id = job.get("user_id")
                if user_id and self._active_job_ids.get(user_id) == job_id:
                    self._active_job_ids.pop(user_id, None)

            return dict(job)

    async def get_active_job_for_lecture(self, lecture_id: int) -> dict[str, Any] | None:
        async with self._lock:
            for job in self._jobs.values():
                if job["status"] in self.terminal_statuses:
                    continue
                job_lecture_id = job.get("lecture_id")
                if job_lecture_id is None:
                    continue
                if int(job_lecture_id) == lecture_id:
                    return dict(job)
            return None

    async def add_raw_event(self, job_id: str, event_name: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            event_id = int(job["next_event_id"])
            job["next_event_id"] = event_id + 1
            event_payload = dict(payload)
            event_payload["event_id"] = event_id
            job["events"].append({
                "id": event_id,
                "event": event_name,
                "payload": event_payload,
            })
            if len(job["events"]) > 2000:
                job["events"] = job["events"][-1000:]

    async def get_job_snapshot_and_events(
        self,
        job_id: str,
        *,
        after_event_id: int,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None, []

            events = [
                {
                    "id": int(evt["id"]),
                    "event": str(evt["event"]),
                    "payload": dict(evt["payload"]),
                }
                for evt in job["events"]
                if int(evt["id"]) > after_event_id
            ]
            return dict(job), events
