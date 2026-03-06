import { useEffect, useRef, useState } from "react";
import { useRegenerationJobController } from "../hooks/useRegenerationJobController";
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
  const [error, setError] = useState<string | null>(null);
  const latestStatusRef = useRef(jobStatus);
  const { attachToJob, job, stop } = useRegenerationJobController({
    onDone: async (_lectureId, status) => {
      setError(null);
      latestStatusRef.current = status;
    },
    onError: (message, status) => {
      if (status) {
        latestStatusRef.current = status;
      }
      setError(message);
    },
  });
  const status = job ?? latestStatusRef.current;

  useEffect(() => {
    latestStatusRef.current = jobStatus;
  }, [jobStatus, latestStatusRef]);

  useEffect(() => {
    if (jobStatus.status === "done" || jobStatus.status === "error") {
      return;
    }

    attachToJob(jobStatus.job_id, jobStatus.lecture_id);
    return stop;
  }, [attachToJob, jobStatus.job_id, jobStatus.lecture_id, jobStatus.status, stop]);

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
