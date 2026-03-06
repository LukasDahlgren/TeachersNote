import { useEffect, useRef, useState } from "react";
import { chatWithLecture, type ChatMessage } from "../api";

type PresetCopy = {
  title: string;
  description: string;
  message: string;
};

type PresetDefinition = {
  id: string;
  copy: PresetCopy;
};

const CHAT_PRESETS: PresetDefinition[] = [
  {
    id: "exam-important",
    copy: {
      title: "Viktigt till tentan",
      description: "Rangordna de viktigaste punkterna och motivera dem kort.",
      message: "Vad är viktigast från den här föreläsningen inför tentan? Rangordna de 5 viktigaste punkterna och förklara dem kort.",
    },
  },
  {
    id: "likely-exam-questions",
    copy: {
      title: "Troliga tentafrågor",
      description: "Skapa sannolika frågor med korta modellsvar.",
      message: "Skapa 5 troliga tentafrågor från den här föreläsningen och ge korta modellsvar.",
    },
  },
  {
    id: "quick-summary",
    copy: {
      title: "Snabb sammanfattning",
      description: "Sammanfatta innehållet i fem korta punkter.",
      message: "Sammanfatta den här föreläsningen i 5 korta punkter.",
    },
  },
  {
    id: "explain-simply",
    copy: {
      title: "Förklara enkelt",
      description: "Bryt ner huvudidén så den blir lätt att förstå.",
      message: "Förklara huvudidén i den här föreläsningen enkelt, som om jag lär mig den för första gången.",
    },
  },
  {
    id: "quiz-me",
    copy: {
      title: "Förhör mig",
      description: "Ställ en fråga i taget och vänta in mitt svar.",
      message: "Förhör mig på den här föreläsningen en fråga i taget. Vänta på mitt svar innan du ger facit.",
    },
  },
  {
    id: "common-mistakes",
    copy: {
      title: "Vanliga misstag",
      description: "Lyft de vanligaste missförstånden att undvika.",
      message: "Vilka är de vanligaste misstagen eller missförstånden som studenter kan ha om den här föreläsningen?",
    },
  },
];

/** Renders basic markdown: **bold**, *italic*, `code`, and newlines */
function renderMarkdown(text: string): React.ReactNode[] {
  // Split on the patterns we handle
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\n)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**"))
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*"))
      return <em key={i}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`"))
      return <code key={i} className="chat-inline-code">{part.slice(1, -1)}</code>;
    if (part === "\n")
      return <br key={i} />;
    return part;
  });
}
interface Props {
  lectureId: number;
  expanded: boolean;
  onExpand: () => void;
  onCollapse: () => void;
  prefillText?: string | null;
  consoleVisible?: boolean;
}

export default function ChatPanel({ lectureId, expanded, onExpand, onCollapse, prefillText, consoleVisible }: Props) {
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

  // When prefill arrives, expand and pre-fill input
  useEffect(() => {
    if (prefillText && prefillText !== lastPrefill) {
      setLastPrefill(prefillText);
      setInput(`About "${prefillText}": `);
      onExpand();
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [prefillText, lastPrefill, onExpand]);

  // Focus input when freshly expanded
  useEffect(() => {
    if (expanded) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [expanded]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, loading]);

  async function sendMessage(text: string) {
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
      const reply = await chatWithLecture(lectureId, trimmed, null, history);
      if (requestIdRef.current !== requestId) return;
      setHistory([...nextHistory, { role: "assistant", content: reply }]);
    } catch (error) {
      if (requestIdRef.current !== requestId) return;
      setError(error instanceof Error ? error.message : "Failed to get a response. Please try again.");
    } finally {
      if (requestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }

  function clearChat() {
    requestIdRef.current += 1;
    setHistory([]);
    setInput("");
    setBubbleInput("");
    setLoading(false);
    setError(null);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  }

  function handleBubbleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onExpand();
    if (bubbleInput.trim()) {
      void sendMessage(bubbleInput);
      setBubbleInput("");
    }
  }

  const messageCount = Math.ceil(history.length / 2);
  const isEmptyState = history.length === 0;
  const canClearChat = history.length > 0 || input.trim() !== "" || loading || error !== null;

  useEffect(() => {
    if (expanded) {
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [expanded, isEmptyState]);

  function renderPresetSection(layout: "empty" | "docked") {
    return (
      <section className={`chat-preset-section chat-preset-section--${layout}`} aria-label="Preset prompts">
        <div className="chat-preset-section__header">
          <div>
            <p className="chat-preset-section__eyebrow">Preset prompts</p>
            <h3 className="chat-preset-section__title">Keep these ready at all times</h3>
          </div>
          <div className="chat-preset-section__header-right">
            <p className="chat-preset-section__hint">Tap a card to send it instantly.</p>
            <button
              type="button"
              className="chat-preset-toggle"
              onClick={() => setPresetsOpen((o) => !o)}
              aria-expanded={presetsOpen}
              aria-label={presetsOpen ? "Collapse preset prompts" : "Expand preset prompts"}
            >
              {presetsOpen ? "▲" : "▼"}
            </button>
          </div>
        </div>
        {presetsOpen && (
          <div className="chat-preset-grid">
            {CHAT_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className="chat-preset-card"
                onClick={() => void sendMessage(preset.copy.message)}
                disabled={loading}
              >
                <span className="chat-preset-card__title">{preset.copy.title}</span>
                <span className="chat-preset-card__description">{preset.copy.description}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    );
  }

  function renderComposer(layout: "empty" | "docked") {
    const centered = layout === "empty";
    return (
      <div className={`chat-composer chat-composer--${layout}`}>
        {centered && (
          <div className="chat-composer-copy">
            <h2 className="chat-composer-copy__title">Ask anything about this lecture</h2>
            <p className="chat-composer-copy__text">Start with your own question or use one of the preset prompts below.</p>
          </div>
        )}
        <div className={`chat-panel-input-row${centered ? " chat-panel-input-row--centered" : ""}`}>
          <textarea
            ref={inputRef}
            className="chat-panel-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question… (Enter to send)"
            rows={centered ? 3 : 2}
            disabled={loading}
          />
          <button
            type="button"
            className="chat-panel-send"
            onClick={() => void sendMessage(input)}
            disabled={loading || !input.trim()}
          >
            ↑
          </button>
        </div>
      </div>
    );
  }

  if (!expanded) {
    const bubbleCls = `chat-bubble-form${consoleVisible ? " chat-bubble-form--console" : ""}`;
    return (
      <form className={bubbleCls} onSubmit={handleBubbleSubmit}>
        <input
          className="chat-bubble-input"
          value={bubbleInput}
          onChange={(e) => setBubbleInput(e.target.value)}
          placeholder={messageCount > 0 ? `💬 Ask AI · ${messageCount}` : "💬 Ask AI…"}
        />
        <button
          type="button"
          className="chat-bubble-open-btn"
          onClick={onExpand}
          aria-label="Open chat"
          title="Open chat"
        >
          ↑
        </button>
      </form>
    );
  }

  return (
    <div className="chat-panel">
      <div className="chat-panel-header">
        <span>💬 Ask AI</span>
        <div className="chat-panel-header-actions">
          <button
            type="button"
            className="chat-panel-clear"
            onClick={clearChat}
            disabled={!canClearChat}
          >
            Clear
          </button>
          <button type="button" className="chat-panel-close" onClick={onCollapse} aria-label="Close chat">✕</button>
        </div>
      </div>

      {isEmptyState ? (
        <div className="chat-panel-body chat-panel-body--empty">
          <div className="chat-panel-empty-layout">
            {renderComposer("empty")}
            {renderPresetSection("empty")}
          </div>
        </div>
      ) : (
        <div className="chat-panel-body chat-panel-body--active">
          <div className="chat-panel-messages">
            {history.map((msg, i) => (
              <div key={i} className={`chat-bubble chat-bubble--${msg.role}`}>
                {msg.role === "assistant" ? renderMarkdown(msg.content) : msg.content}
              </div>
            ))}
            {loading && (
              <div className="chat-bubble chat-bubble--assistant chat-bubble--loading">
                <span className="spinner spinner--dark-sm" />
              </div>
            )}
            {error && <p className="chat-panel-error">{error}</p>}
            <div ref={bottomRef} />
          </div>
          <div className="chat-panel-footer">
            {renderPresetSection("docked")}
            {renderComposer("docked")}
          </div>
        </div>
      )}
    </div>
  );
}
