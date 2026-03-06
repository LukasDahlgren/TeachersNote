import { ApiError, apiFetch, readBody } from "./client";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export async function chatWithLecture(
  lectureId: number,
  message: string,
  selectedText: string | null,
  history: ChatMessage[],
): Promise<string> {
  const res = await apiFetch(`/lectures/${lectureId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, selected_text: selectedText, history }),
  });
  const data = await readBody(res);
  if (!res.ok) {
    const detail = typeof data === "object" && data !== null && "detail" in data && typeof data.detail === "string"
      ? data.detail
      : typeof data === "string" && data.trim()
        ? data
        : "Failed to get a response. Please try again.";
    throw new ApiError(res.status, detail, data);
  }
  if (!data || typeof data !== "object" || !("reply" in data) || typeof data.reply !== "string") {
    throw new Error("Unexpected chat response from server.");
  }
  return data.reply as string;
}
