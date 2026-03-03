import { useEffect, useRef, useState } from "react";
import {
  type UploadRecordingInput,
} from "../types";

interface ConsoleEntry {
  id: number;
  message: string;
  done?: boolean;
}

interface Props {
  onSubmit: (pdf: File, recording: UploadRecordingInput) => void;
  loading: boolean;
  onRunDemo: () => void;
  progressPct?: number | null;
  consoleEntries?: ConsoleEntry[];
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

export default function UploadForm({ onSubmit, loading, onRunDemo, progressPct, consoleEntries }: Props) {
  const consoleEndRef = useRef<HTMLDivElement>(null);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [pdfDragOver, setPdfDragOver] = useState(false);
  const [audioDragOver, setAudioDragOver] = useState(false);
  const [error, setError] = useState("");
  const [showHowItWorks, setShowHowItWorks] = useState(false);

  const pdfInputRef = useRef<HTMLInputElement>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [consoleEntries]);

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
      setError("");
      setFile(file);
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
    if (!pdfFile) {
      setError("Please select a PDF file for slides.");
      return;
    }
    if (!audioFile) {
      setError("Please select an audio or video file.");
      return;
    }

    setError("");
    onSubmit(pdfFile, { type: "file", file: audioFile });
  }

  return (
    <form className={`upload-form${loading ? " upload-form--loading" : ""}`} onSubmit={handleSubmit}>
      <h1 className="form-title">TeachersNote</h1>
      <p className="form-subtitle">
        Upload lecture slides (PDF) and add a recording file to generate an aligned transcript.
      </p>

      <div className="form-info-box">
        <button
          type="button"
          className="form-info-box-header"
          onClick={() => setShowHowItWorks(!showHowItWorks)}
          aria-expanded={showHowItWorks}
        >
          <span className="form-info-box-title">How it works</span>
          <span className={`form-info-box-icon ${showHowItWorks ? "expanded" : ""}`}>▼</span>
        </button>
        {showHowItWorks && (
          <div className="form-info-box-content">
            <p className="form-info-box-text">
              Upload your lecture slides (PDF) and recording. The system extracts slide content, transcribes audio,
              aligns transcript to slides, and creates a temporary lecture name from the first slide. Admin sets the
              final canonical name before approval.
            </p>
            <button
              type="button"
              className="form-info-box-demo-btn"
              onClick={onRunDemo}
              disabled={loading}
            >
              Show demo
            </button>
          </div>
        )}
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
          disabled={
            loading
            || !pdfFile
            || !audioFile
          }
        >
          {loading ? <span className="spinner spinner--dark" /> : "Process Lecture"}
        </button>
      </div>

      {loading && (
        <p className="upload-wait-hint">Processing may take a few minutes depending on the size of your recording.</p>
      )}

      {loading && (
        <div className="upload-progress">
          <div className="upload-progress-bar">
            <div
              className="upload-progress-fill"
              style={{ width: `${progressPct ?? 0}%` }}
            />
          </div>
          <div className="upload-console">
            {(consoleEntries ?? []).length === 0 ? (
              <span className="upload-console-line upload-console-line--dim">Waiting...</span>
            ) : (
              (consoleEntries ?? []).map((entry) => (
                <span key={entry.id} className={`upload-console-line${entry.done ? " upload-console-line--done" : ""}`}>
                  <span className="upload-console-text">{entry.message}</span>
                  {entry.done && <span className="upload-console-check">✓</span>}
                </span>
              ))
            )}
            <div ref={consoleEndRef} />
          </div>
        </div>
      )}
    </form>
  );
}
