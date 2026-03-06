import { useEffect, useRef, useState, type ReactNode } from "react";
import { isEnrichedSlideInvalid, type Segment, type EnrichedSlide } from "../types";

interface Props {
  segments: Segment[];
  enriched?: EnrichedSlide;
  isEnriching?: boolean;
  onAskAI?: (selectedText: string) => void;
  showTranscriptTab?: boolean;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

const BULLET_PREFIX_REGEX = /^(?:[-*•]\s+|\d+[.)]\s+)/;
const BOLD_MARKER_REGEX = /\*\*(.+?)\*\*/g;

function splitBulletLines(text: string): string[] {
  const lines = text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const items: string[] = [];
  let hasPrefixedBullets = false;
  for (const line of lines) {
    const match = line.match(BULLET_PREFIX_REGEX);
    if (match) {
      hasPrefixedBullets = true;
      const item = line.slice(match[0].length).trim();
      if (item) items.push(item);
      continue;
    }
    if (hasPrefixedBullets && items.length > 0) {
      items[items.length - 1] = `${items[items.length - 1]} ${line}`.trim();
    }
  }

  return hasPrefixedBullets ? items : [];
}

function splitSentenceBullets(text: string): string[] {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return [];
  return compact
    .split(/(?<=[.!?])\s+|;\s+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseLecturerBullets(text: string): string[] {
  const normalized = text.trim();
  if (!normalized) return [];

  const prefixed = splitBulletLines(normalized);
  if (prefixed.length > 0) return prefixed;

  const lines = normalized
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length > 1) return lines;

  const sentenceBullets = splitSentenceBullets(normalized);
  return sentenceBullets.length > 0 ? sentenceBullets : [normalized];
}

function parseSlideContentBullets(text: string): string[] {
  const normalized = text.trim();
  if (!normalized) return [];

  const prefixed = splitBulletLines(normalized);
  if (prefixed.length > 0) return prefixed;

  const lines = normalized
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.length > 1 ? lines : [];
}

function renderWithBold(text: string): ReactNode {
  if (!text.includes("**")) return text;

  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let boldKey = 0;

  for (const match of text.matchAll(BOLD_MARKER_REGEX)) {
    const index = match.index ?? -1;
    if (index < 0) continue;

    if (index > lastIndex) {
      nodes.push(text.slice(lastIndex, index));
    }

    const boldPart = match[1] ?? "";
    if (boldPart) {
      nodes.push(<strong key={`bold-${boldKey}`}>{boldPart}</strong>);
      boldKey += 1;
    }

    lastIndex = index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes.length > 0 ? nodes : text;
}

export default function TranscriptPanel({
  segments,
  enriched,
  isEnriching,
  onAskAI,
  showTranscriptTab = true,
}: Props) {
  const topRef = useRef<HTMLDivElement>(null);
  const notesRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<"transcript" | "notes">("notes");
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; text: string } | null>(null);
  const notesInvalid = isEnrichedSlideInvalid(enriched);
  const lecturerBullets = enriched?.lecturer_additions
    ? parseLecturerBullets(enriched.lecturer_additions)
    : [];
  const slideContentBullets = enriched?.slide_content
    ? parseSlideContentBullets(enriched.slide_content)
    : [];

  useEffect(() => {
    topRef.current?.scrollIntoView();
  }, [segments]);

  // Hide context menu on outside click
  useEffect(() => {
    if (!contextMenu) return;
    function onDown() { setContextMenu(null); }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [contextMenu]);

  function handleNotesMouseUp(e: React.MouseEvent) {
    if (!onAskAI) return;
    const selection = window.getSelection();
    const text = selection?.toString().trim();
    if (!text || text.length < 3) return;
    // Only show menu if selection is within the notes area
    if (notesRef.current && !notesRef.current.contains(selection?.anchorNode ?? null)) return;
    setContextMenu({ x: e.clientX, y: e.clientY, text });
  }

  function handleAskAI() {
    if (!contextMenu) return;
    onAskAI?.(contextMenu.text);
    window.getSelection()?.removeAllRanges();
    setContextMenu(null);
  }


  return (
    <div className="transcript-panel">
      <div ref={topRef} />
      {showTranscriptTab && (
        <div className="panel-tabs">
          <button
            className={`panel-tab${tab === "notes" ? " active" : ""}`}
            onClick={() => setTab("notes")}
          >
            📝 Notes
          </button>
          <button
            className={`panel-tab${tab === "transcript" ? " active" : ""}`}
            onClick={() => setTab("transcript")}
          >
            🎙 Transcript
          </button>
        </div>
      )}

      {showTranscriptTab && tab === "transcript" && (
        <div className="tab-content">
          {segments.length === 0 ? (
            <p className="empty">No transcript segments for this slide.</p>
          ) : (
            <ul className="transcript-list">
              {segments.map((seg) => (
                <li key={seg.start}>
                  <span className="timestamp">[{formatTime(seg.start)}]</span>
                  <span className="seg-text">{seg.text}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === "notes" && (
        <div className="tab-content" onMouseUp={handleNotesMouseUp}>
          {!enriched && isEnriching ? (
            <div className="notes-pending">
              <span className="spinner spinner--dark-sm" />
              <p className="notes-pending-text">Notes are being generated for this slide...</p>
            </div>
          ) : !enriched ? (
            <p className="empty">No notes for this slide.</p>
          ) : notesInvalid ? (
            <p className="empty">Notes for this slide are invalid or empty. Regenerate is currently unavailable.</p>
          ) : (
            <div className="notes" ref={notesRef}>
              <p className="notes-summary">{renderWithBold(enriched.summary)}</p>

              {enriched.slide_content && (
                <section className="notes-section">
                  <h3>📋 Slide Content</h3>
                  {slideContentBullets.length > 0 ? (
                    <ul className="notes-list slide-content-list">
                      {slideContentBullets.map((item, index) => (
                        <li key={index}>{renderWithBold(item)}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>{renderWithBold(enriched.slide_content)}</p>
                  )}
                </section>
              )}

              {enriched.lecturer_additions && (
                <section className="notes-section">
                  <h3>🗣 Lecturer Notes</h3>
                  {lecturerBullets.length > 0 ? (
                    <ul className="notes-list lecturer-list">
                      {lecturerBullets.map((item, index) => (
                        <li key={index}>{renderWithBold(item)}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>{renderWithBold(enriched.lecturer_additions)}</p>
                  )}
                </section>
              )}

              {enriched.key_takeaways?.length > 0 && (
                <section className="notes-section">
                  <h3>✅ Key Takeaways</h3>
                  <ul className="takeaways-list">
                    {enriched.key_takeaways.map((t, i) => (
                      <li key={i}>{renderWithBold(t)}</li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </div>
      )}

      {contextMenu && (
        <div
          className="ask-ai-context-menu"
          style={{ top: contextMenu.y + 6, left: contextMenu.x }}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={handleAskAI}
        >
          💬 Ask AI about this
        </div>
      )}
    </div>
  );
}
