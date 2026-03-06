import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any


TERMINAL_JOB_STATUSES = frozenset({"done", "error"})


class RegenerationJobStore:
    def __init__(self, *, ttl_seconds: int, terminal_statuses: set[str] | frozenset[str] = TERMINAL_JOB_STATUSES):
        self.ttl_seconds = ttl_seconds
        self.terminal_statuses = frozenset(terminal_statuses)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active_job_by_lecture: dict[int, str] = {}
        self._lock = asyncio.Lock()

    def public_state(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": job["job_id"],
            "lecture_id": job["lecture_id"],
            "status": job["status"],
            "total_slides": job["total_slides"],
            "completed_slides": job["completed_slides"],
            "current_slide": job["current_slide"],
            "regenerated_slides": job["regenerated_slides"],
            "error": job["error"],
            "updated_at": datetime.fromtimestamp(job["updated_at"], tz=timezone.utc).isoformat(),
        }

    def sse_event(self, event_name: str, payload: dict[str, Any]) -> str:
        return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def cleanup_expired_jobs(self, *, now: float | None = None) -> None:
        current_time = time.time() if now is None else now
        async with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job["status"] in self.terminal_statuses and (current_time - float(job["updated_at"])) > self.ttl_seconds
            ]
            for job_id in expired:
                lecture_id = int(self._jobs[job_id]["lecture_id"])
                if self._active_job_by_lecture.get(lecture_id) == job_id:
                    self._active_job_by_lecture.pop(lecture_id, None)
                self._jobs.pop(job_id, None)

    async def get_job_snapshot(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    async def get_active_job_for_lecture(self, lecture_id: int) -> dict[str, Any] | None:
        async with self._lock:
            job_id = self._active_job_by_lecture.get(lecture_id)
            if not job_id:
                return None
            job = self._jobs.get(job_id)
            if not job or job["status"] in self.terminal_statuses:
                self._active_job_by_lecture.pop(lecture_id, None)
                return None
            return dict(job)

    async def create_job(self, lecture_id: int, total_slides: int) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        now = time.time()
        job = {
            "job_id": job_id,
            "lecture_id": lecture_id,
            "status": "queued",
            "total_slides": total_slides,
            "completed_slides": 0,
            "current_slide": None,
            "regenerated_slides": 0,
            "error": None,
            "updated_at": now,
            "version": 0,
        }
        async with self._lock:
            self._jobs[job_id] = job
            self._active_job_by_lecture[lecture_id] = job_id
        return dict(job)

    async def update_job(self, job_id: str, **updates: Any) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.update(updates)
            job["updated_at"] = time.time()
            job["version"] = int(job["version"]) + 1
            if job["status"] in self.terminal_statuses:
                lecture_id = int(job["lecture_id"])
                if self._active_job_by_lecture.get(lecture_id) == job_id:
                    self._active_job_by_lecture.pop(lecture_id, None)
            return dict(job)
