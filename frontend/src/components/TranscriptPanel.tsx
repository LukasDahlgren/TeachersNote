import { useEffect, useRef, useState } from "react";
import type { Segment, EnrichedSlide } from "../types";

interface Props {
  segments: Segment[];
  enriched?: EnrichedSlide;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

export default function TranscriptPanel({ segments, enriched }: Props) {
  const topRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<"transcript" | "notes">("notes");

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
          ) : (
            <div className="notes">
              <p className="notes-summary">{enriched.summary}</p>

              {enriched.slide_content && (
                <section className="notes-section">
                  <h3>📋 Slide Content</h3>
                  <p>{enriched.slide_content}</p>
                </section>
              )}

              {enriched.lecturer_additions && (
                <section className="notes-section">
                  <h3>🗣 Lecturer Notes</h3>
                  <p>{enriched.lecturer_additions}</p>
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
