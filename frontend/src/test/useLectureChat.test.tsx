import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useLectureChat } from "../hooks/useLectureChat";

describe("useLectureChat", () => {
  it("preserves the current history semantics when sending a message", async () => {
    const requestMessage = vi.fn().mockResolvedValue("assistant reply");
    const onExpand = vi.fn();
    const { result } = renderHook(() => useLectureChat({
      lectureId: 12,
      expanded: true,
      onExpand,
      prefillText: null,
      requestMessage,
    }));

    await act(async () => {
      await result.current.sendMessage("What matters?");
    });

    await waitFor(() => {
      expect(requestMessage).toHaveBeenCalledWith(12, "What matters?", null, []);
    });
    expect(result.current.history).toEqual([
      { role: "user", content: "What matters?" },
      { role: "assistant", content: "assistant reply" },
    ]);
  });
});
