import { useEffect, useRef } from "react";
import { buildAssetUrl } from "../api";
import type { UploadProcessJobStatus } from "../types";

interface ConsoleEntry {
  id: number;
  message: string;
  done?: boolean;
}

interface Props {
  job: UploadProcessJobStatus | null;
  consoleEntries: ConsoleEntry[];
  statusLabel: string;
  isStarting: boolean;
  doneData: { lectureId: number; downloadUrl: string | null } | null;
  onDismiss: () => void;
  onOpenLecture: (id: number) => void;
}

export default function ProcessingConsoleOverlay({
  job,
  consoleEntries,
  statusLabel,
  isStarting,
  doneData,
  onDismiss,
  onOpenLecture,
}: Props) {
  const consoleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = consoleRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [consoleEntries]);

  const isDone = doneData !== null;
  const isError = job?.status === "error";
  const downloadHref = doneData?.downloadUrl ? buildAssetUrl(doneData.downloadUrl) : undefined;

  return (
    <div className="processing-console-overlay">
      <button
        type="button"
        className="processing-console-overlay-close"
        onClick={onDismiss}
        aria-label="Dismiss"
      >
        ✕
      </button>

      {isStarting && (
        <div className="processing-console-overlay-body processing-console-overlay-starting">
          <span className="processing-console-overlay-spinner" />
          <span>Starting...</span>
        </div>
      )}

      {!isStarting && !isDone && !isError && (
        <div className="processing-console-overlay-body">
          {statusLabel && (
            <div className="processing-console-overlay-status">{statusLabel}</div>
          )}
          <div className="processing-console-overlay-progress-bar">
            <div
              className="processing-console-overlay-progress-fill"
              style={{ width: `${job?.progress_pct ?? 0}%` }}
            />
          </div>
          <div className="upload-console processing-console-overlay-console" ref={consoleRef}>
            {consoleEntries.length === 0 ? (
              <span className="upload-console-line upload-console-line--dim">Uploading lecture...</span>
            ) : (
              consoleEntries.map((entry) => (
                <span
                  key={entry.id}
                  className={`upload-console-line${entry.done ? " upload-console-line--done" : ""}`}
                >
                  <span className="upload-console-text">{entry.message}</span>
                  {entry.done && <span className="upload-console-check">✓</span>}
                </span>
              ))
            )}
          </div>
        </div>
      )}

      {isError && !isDone && (
        <div className="processing-console-overlay-body processing-console-overlay-error">
          <div className="processing-console-overlay-error-content">
            <span className="processing-console-overlay-error-icon">✗</span>
            <span className="processing-console-overlay-error-text">
              {job?.error ?? "Processing failed."}
            </span>
          </div>
          <button
            type="button"
            className="processing-console-overlay-dismiss-btn"
            onClick={onDismiss}
          >
            Dismiss
          </button>
        </div>
      )}

      {isDone && (
        <div className="processing-console-overlay-body processing-console-overlay-done">
          <div className="processing-console-overlay-done-header">
            <span className="processing-console-overlay-done-icon">✓</span>
            <span className="processing-console-overlay-done-text">Lecture ready!</span>
          </div>
          <div className="processing-console-overlay-done-actions">
            {downloadHref && (
              <a
                href={downloadHref}
                download
                className="processing-console-overlay-download-btn"
              >
                Download PPTX
              </a>
            )}
            <button
              type="button"
              className="processing-console-overlay-open-btn"
              onClick={() => onOpenLecture(doneData.lectureId)}
            >
              Open Lecture
            </button>
            <button
              type="button"
              className="processing-console-overlay-dismiss-btn"
              onClick={onDismiss}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
