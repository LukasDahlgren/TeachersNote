import { useEffect, useRef } from "react";
import type { Segment } from "../types";

interface Props {
  segments: Segment[];
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

export default function TranscriptPanel({ segments }: Props) {
  const topRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    topRef.current?.scrollIntoView();
  }, [segments]);

  return (
    <div className="transcript-panel">
      <div ref={topRef} />
      <h2>Transcript</h2>
      {segments.length === 0 ? (
        <p className="empty">No transcript segments for this slide.</p>
      ) : (
        <ul>
          {segments.map((seg, i) => (
            <li key={i}>
              <span className="timestamp">[{formatTime(seg.start)}]</span>
              <span className="seg-text">{seg.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
