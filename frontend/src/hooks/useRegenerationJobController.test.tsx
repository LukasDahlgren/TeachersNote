import { renderHook, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useRegenerationJobController } from "./useRegenerationJobController";
import type { RegenerateNotesJobStatus } from "../types";

const DONE_JOB: RegenerateNotesJobStatus = {
  job_id: "regen-1",
  lecture_id: 44,
  status: "done",
  total_slides: 3,
  completed_slides: 3,
  current_slide: null,
  regenerated_slides: 2,
  error: null,
  updated_at: "2026-03-06T10:00:00Z",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useRegenerationJobController", () => {
  it("forwards done events to the completion callback", async () => {
    let handlers:
      | {
        onDone?: (event: RegenerateNotesJobStatus) => void;
      }
      | undefined;

    const onDone = vi.fn().mockResolvedValue(undefined);
    const subscribeToRegenerateNotesEvents = vi.fn((_jobId, nextHandlers) => {
      handlers = nextHandlers;
      return () => {};
    });

    const { result, unmount } = renderHook(() => useRegenerationJobController({
      onDone,
      subscribeToRegenerateNotesEvents,
    }));

    act(() => {
      result.current.attachToJob("regen-1", 44);
    });

    await act(async () => {
      await handlers?.onDone?.(DONE_JOB);
    });

    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledWith(44, DONE_JOB);
    expect(result.current.job).toEqual(DONE_JOB);

    unmount();
  });
});
