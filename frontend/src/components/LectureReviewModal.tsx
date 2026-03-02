import { useCallback, useEffect, useState } from "react";
import { approveLecture, buildAssetUrl, getLecture, rejectLecture } from "../api";
import type { LectureDetail, TeachersNoteSummary } from "../types";
import ConfirmDialog from "./ConfirmDialog";
import SlideViewer from "./SlideViewer";
import TranscriptPanel from "./TranscriptPanel";
import "../LectureReviewModal.css";

interface Props {
  lecture: TeachersNoteSummary;
  onApproved: (id: number) => void;
  onRejected: (id: number) => void;
  onClose: () => void;
}

export default function LectureReviewModal({ lecture, onApproved, onRejected, onClose }: Props) {
  const [data, setData] = useState<LectureDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeSlide, setActiveSlide] = useState(0);
  const [actionInFlight, setActionInFlight] = useState<"approve" | "reject" | null>(null);
  const [confirmRejectOpen, setConfirmRejectOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getLecture(lecture.id)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Failed to load lecture.");
      });
    return () => { cancelled = true; };
  }, [lecture.id]);

  const onPrev = useCallback(() => setActiveSlide((s) => Math.max(0, s - 1)), []);
  const onNext = useCallback(() => {
    if (!data) return;
    setActiveSlide((s) => Math.min(data.slides.length - 1, s + 1));
  }, [data]);

  async function handleApprove() {
    setActionInFlight("approve");
    try {
      await approveLecture(lecture.id);
      onApproved(lecture.id);
    } catch {
      setActionInFlight(null);
    }
  }

  async function handleReject() {
    setActionInFlight("reject");
    try {
      await rejectLecture(lecture.id);
      onRejected(lecture.id);
    } catch {
      setActionInFlight(null);
    }
  }

  const alignment = data?.alignment.find((a) => a.slide === activeSlide + 1);
  const segments = alignment
    ? data!.transcript.slice(alignment.start_segment, alignment.end_segment + 1)
    : [];
  const enriched = data?.enhanced?.find((e) => e.slide === activeSlide + 1);
  const pdfUrl = buildAssetUrl(data?.pdf_url);

  return (
    <>
    {confirmRejectOpen && (
      <ConfirmDialog
        message="Reject and delete this lecture?"
        onConfirm={() => { setConfirmRejectOpen(false); void handleReject(); }}
        onCancel={() => setConfirmRejectOpen(false)}
      />
    )}
    <div className="review-overlay" onClick={onClose}>
      <div className="review-modal" onClick={(e) => e.stopPropagation()}>
        <header className="review-header">
          <h2 className="review-header-title">{lecture.name}</h2>
          <div className="review-header-actions">
            <button
              className="review-approve-btn"
              disabled={actionInFlight !== null || data === null}
              onClick={() => void handleApprove()}
            >
              {actionInFlight === "approve" ? "Approving…" : "Approve"}
            </button>
            <button
              className="review-reject-btn"
              disabled={actionInFlight !== null || data === null}
              onClick={() => setConfirmRejectOpen(true)}
            >
              {actionInFlight === "reject" ? "Rejecting…" : "Reject"}
            </button>
            <button className="review-close-btn" onClick={onClose}>
              ✕ Close
            </button>
          </div>
        </header>

        <div className="review-body">
          {!data && !loadError && (
            <div className="review-loading">Loading lecture…</div>
          )}
          {loadError && (
            <div className="review-error">{loadError}</div>
          )}
          {data && (
            <div className="review-results-body">
              <SlideViewer
                slideText={data.slides[activeSlide]?.text ?? ""}
                slideNumber={activeSlide + 1}
                total={data.slides.length}
                onPrev={onPrev}
                onNext={onNext}
                pdfUrl={pdfUrl}
              />
              <TranscriptPanel segments={segments} enriched={enriched} />
            </div>
          )}
        </div>
      </div>
    </div>
    </>
  );
}
