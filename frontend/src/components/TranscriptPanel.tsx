import { useEffect, useRef, useState } from "react";
import { isEnrichedSlideInvalid, type Segment, type EnrichedSlide } from "../types";

interface Props {
  segments: Segment[];
  enriched?: EnrichedSlide;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

const BULLET_PREFIX_REGEX = /^(?:[-*•]\s+|\d+[.)]\s+)/;

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

export default function TranscriptPanel({ segments, enriched }: Props) {
  const topRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<"transcript" | "notes">("notes");
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

  return (
    <div className="transcript-panel">
      <div ref={topRef} />
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

      {tab === "transcript" && (
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
        <div className="tab-content">
          {!enriched ? (
            <p className="empty">No notes for this slide.</p>
          ) : notesInvalid ? (
            <p className="empty">Notes for this slide are invalid or empty. Regenerate is currently unavailable.</p>
          ) : (
            <div className="notes">
              <p className="notes-summary">{enriched.summary}</p>

              {enriched.slide_content && (
                <section className="notes-section">
                  <h3>📋 Slide Content</h3>
                  {slideContentBullets.length > 0 ? (
                    <ul className="notes-list slide-content-list">
                      {slideContentBullets.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>{enriched.slide_content}</p>
                  )}
                </section>
              )}

              {enriched.lecturer_additions && (
                <section className="notes-section">
                  <h3>🗣 Lecturer Notes</h3>
                  {lecturerBullets.length > 0 ? (
                    <ul className="notes-list lecturer-list">
                      {lecturerBullets.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>{enriched.lecturer_additions}</p>
                  )}
                </section>
              )}

              {enriched.key_takeaways?.length > 0 && (
                <section className="notes-section">
                  <h3>✅ Key Takeaways</h3>
                  <ul className="takeaways-list">
                    {enriched.key_takeaways.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
