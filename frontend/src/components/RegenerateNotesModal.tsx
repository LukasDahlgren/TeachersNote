import { useEffect, useState } from "react";
import { subscribeRegenerateNotesEvents } from "../api";
import type { RegenerateNotesJobStatus } from "../types";
import "./RegenerateNotesModal.css";

interface RegenerateNotesModalProps {
  lectureTitle: string;
  jobStatus: RegenerateNotesJobStatus;
  onClose: () => void;
}

export default function RegenerateNotesModal({
  lectureTitle,
  jobStatus,
  onClose,
}: RegenerateNotesModalProps) {
  const [status, setStatus] = useState<RegenerateNotesJobStatus>(jobStatus);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status.status === "done" || status.status === "error") {
      return;
    }

    const unsubscribe = subscribeRegenerateNotesEvents(status.job_id, {
      onProgress: (event) => {
        setStatus(event);
      },
      onDone: (event) => {
        setStatus(event);
      },
      onError: (event) => {
        setStatus(event);
        setError(event.error || "An error occurred during regeneration.");
      },
      onTransportError: () => {
        setError("Connection lost. Please refresh or close this modal.");
      },
    });

    return unsubscribe;
  }, [status.job_id, status.status]);

  const isDone = status.status === "done";
  const isError = status.status === "error";
  const isRunning = status.status === "running" || status.status === "queued";

  const progressPercentage = status.total_slides > 0
    ? Math.round((status.completed_slides / status.total_slides) * 100)
    : 0;

  return (
    <div className="modal-overlay">
      <div className="regenerate-modal">
        <div className="regenerate-modal-header">
          <h2>Regenerating notes: {lectureTitle}</h2>
          {!isRunning && (
            <button className="regenerate-modal-close" onClick={onClose}>
              ✕
            </button>
          )}
        </div>

        <div className="regenerate-modal-body">
          {isRunning && (
            <div className="regenerate-modal-loading">
              <div className="spinner spinner--dark-lg" />
              <p className="regenerate-modal-status">
                {status.status === "queued" ? "Queued..." : `Regenerating: Slide ${status.current_slide ?? "?"}`}
              </p>
            </div>
          )}

          {isDone && (
            <div className="regenerate-modal-success">
              <div className="regenerate-modal-icon">✓</div>
              <p className="regenerate-modal-message">
                Successfully regenerated notes for {status.regenerated_slides} slide{
                  status.regenerated_slides === 1 ? "" : "s"
                }.
              </p>
            </div>
          )}

          {isError && (
            <div className="regenerate-modal-error">
              <div className="regenerate-modal-icon">✕</div>
              <p className="regenerate-modal-message">
                {error || "An error occurred during regeneration."}
              </p>
            </div>
          )}

          <div className="regenerate-modal-progress">
            <div className="regenerate-modal-progress-bar-container">
              <div
                className="regenerate-modal-progress-bar"
                style={{ width: `${progressPercentage}%` }}
              />
            </div>
            <div className="regenerate-modal-progress-text">
              <span>
                {status.completed_slides} / {status.total_slides} slides
              </span>
              <span>{progressPercentage}%</span>
            </div>
          </div>
        </div>

        <div className="regenerate-modal-footer">
          {!isRunning && (
            <button className="regenerate-modal-close-btn" onClick={onClose}>
              {isDone ? "Done" : "Close"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
