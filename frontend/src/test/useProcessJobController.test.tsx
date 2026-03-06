import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useProcessJobController } from "../hooks/useProcessJobController";
import type { UploadProcessJobEvent, UploadProcessJobStatus } from "../types";

function makeStatus(overrides: Partial<UploadProcessJobStatus> = {}): UploadProcessJobStatus {
  return {
    current_stage: "upload",
    error: null,
    job_id: "job-1",
    lecture_id: null,
    pdf_url: null,
    progress_pct: 10,
    status: "running",
    total_slides: null,
    updated_at: "2026-03-06T12:00:00.000Z",
    ...overrides,
  };
}

describe("useProcessJobController", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("migrates the legacy storage key and resumes the running job", async () => {
    const getProcessJobSnapshot = vi.fn().mockResolvedValue(makeStatus());
    const subscribeToProcessJobEvents = vi.fn().mockReturnValue(() => {});
    window.localStorage.setItem("lecture-summary.active-process-job-id", "legacy-job");

    const { result } = renderHook(() => useProcessJobController({
      getProcessJobSnapshot,
      subscribeToProcessJobEvents,
    }));

    await act(async () => {
      await result.current.resumePersistedJob();
    });

    expect(window.localStorage.getItem("teachers-note.active-process-job-id")).toBe("legacy-job");
    expect(window.localStorage.getItem("lecture-summary.active-process-job-id")).toBeNull();
    expect(getProcessJobSnapshot).toHaveBeenCalledWith("legacy-job");
    expect(subscribeToProcessJobEvents).toHaveBeenCalledWith(
      "legacy-job",
      expect.any(Object),
      { lastEventId: 0 },
    );
    expect(result.current.uploadLoadingLabel).toBe("Processing: upload (10%)");
  });

  it("dedupes terminal completion while keeping the latest live slide update", async () => {
    const onDone = vi.fn();
    let handlers: {
      onDone?: (event: UploadProcessJobEvent) => void;
      onSlideEnriched?: (event: UploadProcessJobEvent) => void;
    } | null = null;
    const subscribeToProcessJobEvents = vi.fn().mockImplementation((_jobId, nextHandlers) => {
      handlers = nextHandlers;
      return () => {};
    });

    const { result } = renderHook(() => useProcessJobController({
      onDone,
      subscribeToProcessJobEvents,
    }));

    act(() => {
      result.current.attachToJob("job-1", 0);
    });

    act(() => {
      handlers?.onSlideEnriched?.({
        current_stage: "enrich",
        error: null,
        event_id: 4,
        job_id: "job-1",
        lecture_id: 99,
        message: "slide 3",
        pdf_url: null,
        progress_pct: 80,
        slide: 3,
        slide_content: "old",
        lecturer_additions: "",
        key_takeaways: [],
        status: "running",
        summary: "old",
        total_slides: 10,
        updated_at: "2026-03-06T12:00:00.000Z",
      } as UploadProcessJobEvent);
      handlers?.onSlideEnriched?.({
        current_stage: "enrich",
        error: null,
        event_id: 5,
        job_id: "job-1",
        lecture_id: 99,
        message: "slide 3",
        pdf_url: null,
        progress_pct: 82,
        slide: 3,
        slide_content: "new",
        lecturer_additions: "",
        key_takeaways: [],
        status: "running",
        summary: "new",
        total_slides: 10,
        updated_at: "2026-03-06T12:00:01.000Z",
      } as UploadProcessJobEvent);
      handlers?.onDone?.(makeStatus({ status: "done", progress_pct: 100, lecture_id: 99 }) as UploadProcessJobEvent);
      handlers?.onDone?.(makeStatus({ status: "done", progress_pct: 100, lecture_id: 99 }) as UploadProcessJobEvent);
    });

    await act(async () => {});

    expect(onDone).toHaveBeenCalledTimes(1);
    expect(result.current.liveEnrichedSlides).toEqual([
      expect.objectContaining({ slide: 3, summary: "new", slide_content: "new" }),
    ]);
  });
});
