import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useRegenerationJobController } from "../hooks/useRegenerationJobController";
import type { RegenerateNotesJobStatus } from "../types";

function makeStatus(overrides: Partial<RegenerateNotesJobStatus> = {}): RegenerateNotesJobStatus {
  return {
    completed_slides: 0,
    current_slide: null,
    error: null,
    job_id: "regen-1",
    lecture_id: 7,
    regenerated_slides: 0,
    status: "running",
    total_slides: 4,
    updated_at: "2026-03-06T12:00:00.000Z",
    ...overrides,
  };
}

describe("useRegenerationJobController", () => {
  it("falls back to a snapshot on transport errors and completes through the same callback", async () => {
    const onDone = vi.fn();
    const getRegenerateNotesJobSnapshot = vi.fn().mockResolvedValue(
      makeStatus({ status: "done", completed_slides: 4, regenerated_slides: 2 }),
    );
    let handlers: { onTransportError?: () => void } | null = null;
    const subscribeToRegenerateNotesEvents = vi.fn().mockImplementation((_jobId, nextHandlers) => {
      handlers = nextHandlers;
      return () => {};
    });

    const { result } = renderHook(() => useRegenerationJobController({
      getRegenerateNotesJobSnapshot,
      onDone,
      subscribeToRegenerateNotesEvents,
    }));

    act(() => {
      result.current.attachToJob("regen-1", 7);
    });

    act(() => {
      handlers?.onTransportError?.();
    });

    await waitFor(() => {
      expect(getRegenerateNotesJobSnapshot).toHaveBeenCalledWith("regen-1");
      expect(onDone).toHaveBeenCalledWith(7, expect.objectContaining({ status: "done", regenerated_slides: 2 }));
    });
  });
});
