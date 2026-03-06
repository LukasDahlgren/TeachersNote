import UploadForm from "./UploadForm";

type OverlayPositionStyle = {
  top: string;
  left: string;
};

interface ConsoleEntry {
  id: number;
  message: string;
  done: boolean;
  stage: string;
}

interface NewLectureOverlayProps {
  canRunDemo: boolean;
  consoleEntries: ConsoleEntry[];
  loading: boolean;
  onClose: () => void;
  onRunDemo: () => void;
  onSubmit: (
    pdf: File,
    recording: { type: "file"; file: File } | { type: "url"; url: string },
    courseContext: string | null,
    lectureName: string,
  ) => void;
  open: boolean;
  progressPct: number | null;
  style?: OverlayPositionStyle;
}

export default function NewLectureOverlay({
  canRunDemo,
  consoleEntries,
  loading,
  onClose,
  onRunDemo,
  onSubmit,
  open,
  progressPct,
  style,
}: NewLectureOverlayProps) {
  if (!open) return null;

  return (
    <div className="new-lecture-overlay-scrim" onClick={onClose}>
      <section
        id="new-lecture-overlay-panel"
        className="new-lecture-overlay-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-lecture-overlay-title"
        style={style}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="new-lecture-overlay-header">
          <h2 id="new-lecture-overlay-title" className="new-lecture-overlay-title">New Lecture Upload</h2>
          <button
            type="button"
            className="new-lecture-overlay-close-btn"
            onClick={onClose}
            aria-label="Close upload form"
          >
            ✕
          </button>
        </div>
        <UploadForm
          onSubmit={onSubmit}
          loading={loading}
          canRunDemo={canRunDemo}
          onRunDemo={onRunDemo}
          progressPct={progressPct}
          consoleEntries={consoleEntries}
        />
      </section>
    </div>
  );
}
