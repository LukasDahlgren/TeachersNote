import { renderHook, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useProcessJobController } from "./useProcessJobController";
import type { UploadProcessJobEvent, UploadProcessJobStatus } from "../types";

const RUNNING_JOB: UploadProcessJobStatus = {
  job_id: "job-1",
  status: "running",
  current_stage: "transcribe",
  progress_pct: 42,
  lecture_id: 55,
  total_slides: 12,
  pdf_url: "/pdf/demo.pdf",
  error: null,
  updated_at: "2026-03-06T10:00:00Z",
};

const DONE_EVENT: UploadProcessJobEvent = {
  ...RUNNING_JOB,
  status: "done",
  current_stage: "done",
  progress_pct: 100,
  message: "Processing complete.",
};

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("useProcessJobController", () => {
  it("migrates the legacy storage key and resumes the stored job", async () => {
    localStorage.setItem("legacy-job-key", "job-1");

    const getProcessJobSnapshot = vi.fn().mockResolvedValue(RUNNING_JOB);
    const subscribeToProcessJobEvents = vi.fn((_jobId, _handlers, _options) => () => {});
    const onLectureAdded = vi.fn();

    const { result, unmount } = renderHook(() => useProcessJobController({
      activeProcessJobStorageKey: "primary-job-key",
      legacyActiveProcessJobStorageKey: "legacy-job-key",
      getProcessJobSnapshot,
      subscribeToProcessJobEvents,
      onLectureAdded,
      pollMs: 60_000,
    }));

    await act(async () => {
      await result.current.resumePersistedJob();
    });

    expect(localStorage.getItem("primary-job-key")).toBe("job-1");
    expect(localStorage.getItem("legacy-job-key")).toBeNull();
    expect(getProcessJobSnapshot).toHaveBeenCalledWith("job-1");
    expect(subscribeToProcessJobEvents).toHaveBeenCalledWith(
      "job-1",
      expect.any(Object),
      { lastEventId: 0 },
    );
    expect(result.current.uploadLoadingLabel).toBe("Processing: transcribe (42%)");

    unmount();
  });

  it("handles duplicate done events only once", async () => {
    let handlers:
      | {
        onDone?: (event: UploadProcessJobEvent) => void;
      }
      | undefined;

    const onDone = vi.fn().mockResolvedValue(undefined);
    const subscribeToProcessJobEvents = vi.fn((_jobId, nextHandlers) => {
      handlers = nextHandlers;
      return () => {};
    });

    const { result, unmount } = renderHook(() => useProcessJobController({
      getProcessJobSnapshot: vi.fn(),
      onDone,
      subscribeToProcessJobEvents,
      pollMs: 60_000,
    }));

    act(() => {
      result.current.attachToJob("job-1", 0);
    });

    await act(async () => {
      await handlers?.onDone?.(DONE_EVENT);
      await handlers?.onDone?.(DONE_EVENT);
    });

    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledWith(DONE_EVENT);

    unmount();
  });
});
