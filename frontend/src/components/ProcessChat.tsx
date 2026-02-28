import { useEffect, useRef } from "react";
import type { UploadProcessJobStatus } from "../types";

const PIPELINE_STAGES = ["parse_slides", "transcribe", "align", "enrich", "generate_pptx"] as const;

const STAGE_DISPLAY_NAMES: Record<string, string> = {
  parse_slides: "Parsing slides...",
  transcribe: "Transcribing...",
  align: "Aligning transcript...",
  enrich: "Generating notes...",
  generate_pptx: "Generating presentation...",
};

function formatStage(stage: string): string {
  return STAGE_DISPLAY_NAMES[stage] || stage.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

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
  variant?: "default" | "sidebar";
  statusLabel?: string;
  lectureName?: string | null;
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "";
  }
}

export default function ProcessChat({ entries, job, variant = "default", statusLabel, lectureName }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const emptyMessage = statusLabel?.trim() || "Waiting for backend progress updates...";

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries]);

  return (
    <section className={`process-chat${variant === "sidebar" ? " process-chat--sidebar" : ""}`} aria-live="polite">
      <div className="process-chat-header">
        <div className="process-chat-title-group">
          {lectureName && <span className="process-chat-title">{lectureName}</span>}
          <span className="process-chat-subtitle">
            {job?.current_stage
              ? (() => {
                  const stepIndex = (PIPELINE_STAGES as readonly string[]).indexOf(job.current_stage);
                  const stepLabel = stepIndex >= 0 ? `${stepIndex + 1}/${PIPELINE_STAGES.length}` : "";
                  return `${formatStage(job.current_stage)}${stepLabel ? ` — ${stepLabel}` : ""} · ${job.progress_pct ?? 0}%`;
                })()
              : "Waiting..."
            }
          </span>
        </div>
      </div>
      {variant !== "sidebar" && (
        <div className="process-chat-feed">
          {entries.length === 0 ? (
            <p className="process-chat-empty">{emptyMessage}</p>
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
      )}
    </section>
  );
}
