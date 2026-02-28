import { useRef, useState } from "react";
import { type UploadLectureNamingInput } from "../types";

interface Props {
  onSubmit: (pdf: File, audio: File, naming: UploadLectureNamingInput) => void;
  loading: boolean;
  demoMode: boolean;
  onRunDemo: () => void;
  progressPct?: number | null;
  progressLabel?: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

function PdfIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="5" y="2" width="18" height="24" rx="2" fill="#e5e7eb" stroke="#d1d5db" strokeWidth="1.5" />
      <path d="M19 2v6h6" fill="none" stroke="#d1d5db" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M19 2l6 6" fill="none" stroke="#d1d5db" strokeWidth="1.5" strokeLinejoin="round" />
      <rect x="5" y="2" width="14" height="24" rx="2" fill="#f9fafb" stroke="#d1d5db" strokeWidth="1.5" />
      <path d="M19 2v6h6" fill="#e5e7eb" stroke="#d1d5db" strokeWidth="1.5" strokeLinejoin="round" />
      <line x1="9" y1="13" x2="21" y2="13" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="9" y1="17" x2="21" y2="17" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="9" y1="21" x2="16" y2="21" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function AudioIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="10" cy="22" r="4" fill="#e5e7eb" stroke="#d1d5db" strokeWidth="1.5" />
      <circle cx="24" cy="18" r="4" fill="#e5e7eb" stroke="#d1d5db" strokeWidth="1.5" />
      <line x1="14" y1="22" x2="14" y2="6" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="28" y1="18" x2="28" y2="2" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="14" y1="6" x2="28" y2="2" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function FileSelectedIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="10" cy="10" r="9" fill="#3b82f6" />
      <path d="M6 10l3 3 5-5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const AUDIO_EXTENSIONS = /\.(mp4|mov|webm|wav|m4a|mp3)$/i;

interface DropZoneProps {
  label: string;
  accept: string;
  file: File | null;
  dragOver: boolean;
  loading: boolean;
  icon: React.ReactNode;
  dropTitle: string;
  dropHint: string;
  dropAccepts: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onDrop: (e: React.DragEvent) => void;
  onDragOver: (over: boolean) => void;
  onFileChange: (file: File) => void;
  onClear: () => void;
}

function DropZone({
  label, accept, file, dragOver, loading, icon,
  dropTitle, dropHint, dropAccepts,
  inputRef, onDrop, onDragOver, onFileChange, onClear,
}: DropZoneProps) {
  return (
    <div className="drop-zone-wrapper">
      <div className="drop-zone-label">{label}</div>
      <div
        className={`drop-zone${dragOver ? " drag-over" : ""}${file ? " has-file" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); onDragOver(true); }}
        onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) onDragOver(false); }}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          style={{ display: "none" }}
          disabled={loading}
          onChange={e => { const f = e.target.files?.[0]; if (f) onFileChange(f); }}
        />
        {file ? (
          <div className="file-info">
            <FileSelectedIcon />
            <span className="file-name">{file.name}</span>
            <span className="file-size">{formatBytes(file.size)}</span>
            <button
              type="button"
              className="clear-btn"
              onClick={e => { e.stopPropagation(); onClear(); }}
            >
              ×
            </button>
          </div>
        ) : (
          <div className="drop-prompt">
            {icon}
            <div>
              <div className="drop-title">{dropTitle}</div>
              <div className="drop-hint">{dropHint}</div>
              <div className="drop-accepts">{dropAccepts}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function UploadForm({ onSubmit, loading, demoMode, onRunDemo, progressPct, progressLabel }: Props) {
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [courseid, setCourseid] = useState("");
  const [kind, setKind] = useState("lecture");
  const [lecture, setLecture] = useState("");
  const [year, setYear] = useState("");
  const [pdfDragOver, setPdfDragOver] = useState(false);
  const [audioDragOver, setAudioDragOver] = useState(false);
  const [error, setError] = useState("");
  const pdfInputRef = useRef<HTMLInputElement>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);

  function makeDropHandler(
    mimeCheck: (file: File) => boolean,
    setFile: (file: File) => void,
    setDragOver: (over: boolean) => void,
    errorMsg: string,
  ) {
    return (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (!file) return;
      if (!mimeCheck(file)) { setError(errorMsg); return; }
      setError(""); setFile(file);
    };
  }

  const handlePdfDrop = makeDropHandler(
    (f) => f.type === "application/pdf" || f.name.endsWith(".pdf"),
    setPdfFile,
    setPdfDragOver,
    "Please drop a PDF file for slides.",
  );

  const handleAudioDrop = makeDropHandler(
    (f) => AUDIO_EXTENSIONS.test(f.name),
    setAudioFile,
    setAudioDragOver,
    "Please drop an audio or video file (.mp4, .mov, .webm, .wav, .m4a, .mp3).",
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!pdfFile || !audioFile) {
      setError("Please select both a PDF and an audio file.");
      return;
    }

    const nextCourseid = courseid.trim();
    const nextKind = kind.trim() || "lecture";
    const nextLecture = lecture.trim();
    const nextYear = year.trim();
    if (!nextCourseid || !nextLecture || !nextYear) {
      setError("Please fill in Course ID, Lecture, and Year.");
      return;
    }
    if (!/^\d{4}$/.test(nextYear)) {
      setError("Year must be exactly 4 digits.");
      return;
    }

    setError("");
    onSubmit(pdfFile, audioFile, {
      courseid: nextCourseid,
      kind: nextKind,
      lecture: nextLecture,
      year: nextYear,
    });
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit}>
      <h1 className="form-title">Lecture Summary</h1>
      <p className="form-subtitle">
        Upload lecture slides (PDF) and an audio or video recording to generate an aligned transcript.
      </p>
      {demoMode && (
        <div className="form-demo-hint">
          Demo Mode is on. Processing and regeneration are simulated without API-key calls.
        </div>
      )}

      <div className="naming-fields">
        <div className="naming-field">
          <label className="drop-zone-label" htmlFor="courseid-input">Course ID</label>
          <input
            id="courseid-input"
            className="naming-input"
            type="text"
            value={courseid}
            disabled={loading}
            autoComplete="off"
            onChange={(e) => {
              setCourseid(e.target.value);
              setError("");
            }}
            placeholder="IDSV, PROG2"
          />
        </div>
        <div className="naming-field">
          <label className="drop-zone-label" htmlFor="kind-input">Kind</label>
          <input
            id="kind-input"
            className="naming-input"
            type="text"
            value={kind}
            disabled={loading}
            autoComplete="off"
            onChange={(e) => {
              setKind(e.target.value);
              setError("");
            }}
            placeholder="lecture"
          />
        </div>
        <div className="naming-field">
          <label className="drop-zone-label" htmlFor="lecture-input">Lecture</label>
          <input
            id="lecture-input"
            className="naming-input"
            type="text"
            value={lecture}
            disabled={loading}
            autoComplete="off"
            onChange={(e) => {
              setLecture(e.target.value);
              setError("");
            }}
            placeholder="3"
          />
        </div>
        <div className="naming-field">
          <label className="drop-zone-label" htmlFor="year-input">Year</label>
          <input
            id="year-input"
            className="naming-input"
            type="text"
            value={year}
            disabled={loading}
            autoComplete="off"
            inputMode="numeric"
            pattern="[0-9]{4}"
            maxLength={4}
            onChange={(e) => {
              setYear(e.target.value);
              setError("");
            }}
            placeholder="2026"
          />
        </div>
      </div>

      <DropZone
        label="Slides (PDF)"
        accept=".pdf"
        file={pdfFile}
        dragOver={pdfDragOver}
        loading={loading}
        icon={<PdfIcon />}
        dropTitle="Drop PDF here or click to browse"
        dropHint="Drag and drop your lecture slide deck"
        dropAccepts="Accepts: .pdf"
        inputRef={pdfInputRef}
        onDrop={handlePdfDrop}
        onDragOver={setPdfDragOver}
        onFileChange={file => { setError(""); setPdfFile(file); }}
        onClear={() => { setPdfFile(null); if (pdfInputRef.current) pdfInputRef.current.value = ""; }}
      />

      <DropZone
        label="Video / Audio"
        accept=".mp4,.mov,.webm,.wav,.m4a,.mp3"
        file={audioFile}
        dragOver={audioDragOver}
        loading={loading}
        icon={<AudioIcon />}
        dropTitle="Drop audio/video here or click to browse"
        dropHint="Drag and drop your recording"
        dropAccepts="Accepts: .mp4 .mov .webm .wav .m4a .mp3"
        inputRef={audioInputRef}
        onDrop={handleAudioDrop}
        onDragOver={setAudioDragOver}
        onFileChange={file => { setError(""); setAudioFile(file); }}
        onClear={() => { setAudioFile(null); if (audioInputRef.current) audioInputRef.current.value = ""; }}
      />

      {error && <p className="form-error">{error}</p>}

      <div className="submit-actions">
        <button
          type="submit"
          className="submit-btn"
          disabled={loading || !pdfFile || !audioFile || !courseid.trim() || !lecture.trim() || !year.trim()}
        >
          {loading ? <span className="spinner spinner--dark" /> : "Process Lecture"}
        </button>
        {demoMode && (
          <button
            type="button"
            className="submit-btn submit-btn-secondary"
            onClick={onRunDemo}
            disabled={loading}
          >
            {loading ? <span className="spinner spinner--dark" /> : "Run Demo"}
          </button>
        )}
      </div>

      {loading && (
        <div className="upload-progress">
          <div className="upload-progress-bar">
            <div
              className="upload-progress-fill"
              style={{ width: `${progressPct ?? 0}%` }}
            />
          </div>
          {progressLabel && (
            <span className="upload-progress-label">{progressLabel}</span>
          )}
        </div>
      )}
    </form>
  );
}
