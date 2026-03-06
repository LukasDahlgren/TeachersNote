import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { chatWithLecture, type ChatMessage } from "../api";

export type LectureChatRequester = typeof chatWithLecture;

interface UseLectureChatOptions {
  lectureId: number;
  expanded: boolean;
  onExpand: () => void;
  prefillText?: string | null;
  requestMessage?: LectureChatRequester;
}

export function useLectureChat({
  lectureId,
  expanded,
  onExpand,
  prefillText,
  requestMessage = chatWithLecture,
}: UseLectureChatOptions) {
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [bubbleInput, setBubbleInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastPrefill, setLastPrefill] = useState<string | null>(null);
  const [presetsOpen, setPresetsOpen] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (prefillText && prefillText !== lastPrefill) {
      setLastPrefill(prefillText);
      setInput(`About "${prefillText}": `);
      onExpand();
      window.setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [lastPrefill, onExpand, prefillText]);

  useEffect(() => {
    if (expanded) {
      window.setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [expanded]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, loading]);

  const isEmptyState = history.length === 0;

  useEffect(() => {
    if (expanded) {
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [expanded, isEmptyState]);

  async function sendMessage(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    const userMsg: ChatMessage = { role: "user", content: trimmed };
    const nextHistory = [...history, userMsg];
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setHistory(nextHistory);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const reply = await requestMessage(lectureId, trimmed, null, history);
      if (requestIdRef.current !== requestId) return;
      setHistory([...nextHistory, { role: "assistant", content: reply }]);
    } catch (requestError) {
      if (requestIdRef.current !== requestId) return;
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Failed to get a response. Please try again.",
      );
    } finally {
      if (requestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }

  function clearChat(): void {
    requestIdRef.current += 1;
    setHistory([]);
    setInput("");
    setBubbleInput("");
    setLoading(false);
    setError(null);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage(input);
    }
  }

  function handleBubbleSubmit(event: FormEvent): void {
    event.preventDefault();
    onExpand();
    if (bubbleInput.trim()) {
      void sendMessage(bubbleInput);
      setBubbleInput("");
    }
  }

  return {
    bottomRef,
    bubbleInput,
    canClearChat: history.length > 0 || input.trim() !== "" || loading || error !== null,
    clearChat,
    error,
    handleBubbleSubmit,
    handleKeyDown,
    history,
    input,
    inputRef,
    isEmptyState,
    loading,
    messageCount: Math.ceil(history.length / 2),
    presetsOpen,
    sendMessage,
    setBubbleInput,
    setInput,
    setPresetsOpen,
  };
}
