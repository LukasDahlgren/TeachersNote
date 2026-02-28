import { useEffect, useRef } from "react";
import type { UploadProcessJobStatus } from "../types";

export interface ProcessChatEntry {
  eventId: number;
  type: "progress" | "log" | "done" | "error";
  message: string;
  stage: string;
  progress: number;
  updatedAt: string;
}

interface Props {
  entries: ProcessChatEntry[];
  job: UploadProcessJobStatus | null;
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "";
  }
}

export default function ProcessChat({ entries, job }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries]);

  return (
    <section className="process-chat" aria-live="polite">
      <div className="process-chat-header">
        <span className="process-chat-title">Processing status</span>
        <span className="process-chat-progress">{job?.progress_pct ?? 0}%</span>
      </div>
      <div className="process-chat-feed">
        {entries.length === 0 ? (
          <p className="process-chat-empty">Waiting for backend progress updates...</p>
        ) : (
          entries.map((entry) => (
            <article key={entry.eventId} className={`process-chat-item process-chat-item--${entry.type}`}>
              <div className="process-chat-meta">
                <span>{entry.stage}</span>
                <span>{formatTimestamp(entry.updatedAt)}</span>
              </div>
              <p className="process-chat-message">{entry.message}</p>
            </article>
          ))
        )}
        <div ref={endRef} />
      </div>
    </section>
  );
}
