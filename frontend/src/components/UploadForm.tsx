import { useRef, useState } from "react";

interface Props {
  onSubmit: (pdf: File, audio: File) => void;
  loading: boolean;
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

export default function UploadForm({ onSubmit, loading }: Props) {
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [pdfDragOver, setPdfDragOver] = useState(false);
  const [audioDragOver, setAudioDragOver] = useState(false);
  const [error, setError] = useState("");
  const pdfInputRef = useRef<HTMLInputElement>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);

  function handlePdfDrop(e: React.DragEvent) {
    e.preventDefault();
    setPdfDragOver(false);
    const file = e.dataTransfer.files[0];
    if (!file) return;
    if (file.type !== "application/pdf" && !file.name.endsWith(".pdf")) {
      setError("Please drop a PDF file for slides.");
      return;
    }
    setError("");
    setPdfFile(file);
  }

  function handleAudioDrop(e: React.DragEvent) {
    e.preventDefault();
    setAudioDragOver(false);
    const file = e.dataTransfer.files[0];
    if (!file) return;
    if (!AUDIO_EXTENSIONS.test(file.name)) {
      setError("Please drop an audio or video file (.mp4, .mov, .webm, .wav, .m4a, .mp3).");
      return;
    }
    setError("");
    setAudioFile(file);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!pdfFile || !audioFile) {
      setError("Please select both a PDF and an audio file.");
      return;
    }
    setError("");
    onSubmit(pdfFile, audioFile);
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit}>
      <h1 className="form-title">Lecture Summary</h1>
      <p className="form-subtitle">
        Upload lecture slides (PDF) and an audio or video recording to generate an aligned transcript.
      </p>

      {/* PDF drop zone */}
      <div className="drop-zone-wrapper">
        <div className="drop-zone-label">Slides (PDF)</div>
        <div
          className={`drop-zone${pdfDragOver ? " drag-over" : ""}${pdfFile ? " has-file" : ""}`}
          onClick={() => pdfInputRef.current?.click()}
          onDragOver={e => { e.preventDefault(); setPdfDragOver(true); }}
          onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setPdfDragOver(false); }}
          onDrop={handlePdfDrop}
        >
          <input
            ref={pdfInputRef}
            type="file"
            accept=".pdf"
            style={{ display: "none" }}
            disabled={loading}
            onChange={e => {
              const file = e.target.files?.[0];
              if (file) { setError(""); setPdfFile(file); }
            }}
          />
          {pdfFile ? (
            <div className="file-info">
              <FileSelectedIcon />
              <span className="file-name">{pdfFile.name}</span>
              <span className="file-size">{formatBytes(pdfFile.size)}</span>
              <button
                type="button"
                className="clear-btn"
                onClick={e => {
                  e.stopPropagation();
                  setPdfFile(null);
                  if (pdfInputRef.current) pdfInputRef.current.value = "";
                }}
              >
                ×
              </button>
            </div>
          ) : (
            <div className="drop-prompt">
              <PdfIcon />
              <div>
                <div className="drop-title">Drop PDF here or click to browse</div>
                <div className="drop-hint">Drag and drop your lecture slide deck</div>
                <div className="drop-accepts">Accepts: .pdf</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Audio drop zone */}
      <div className="drop-zone-wrapper">
        <div className="drop-zone-label">Video / Audio</div>
        <div
          className={`drop-zone${audioDragOver ? " drag-over" : ""}${audioFile ? " has-file" : ""}`}
          onClick={() => audioInputRef.current?.click()}
          onDragOver={e => { e.preventDefault(); setAudioDragOver(true); }}
          onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setAudioDragOver(false); }}
          onDrop={handleAudioDrop}
        >
          <input
            ref={audioInputRef}
            type="file"
            accept=".mp4,.mov,.webm,.wav,.m4a,.mp3"
            style={{ display: "none" }}
            disabled={loading}
            onChange={e => {
              const file = e.target.files?.[0];
              if (file) { setError(""); setAudioFile(file); }
            }}
          />
          {audioFile ? (
            <div className="file-info">
              <FileSelectedIcon />
              <span className="file-name">{audioFile.name}</span>
              <span className="file-size">{formatBytes(audioFile.size)}</span>
              <button
                type="button"
                className="clear-btn"
                onClick={e => {
                  e.stopPropagation();
                  setAudioFile(null);
                  if (audioInputRef.current) audioInputRef.current.value = "";
                }}
              >
                ×
              </button>
            </div>
          ) : (
            <div className="drop-prompt">
              <AudioIcon />
              <div>
                <div className="drop-title">Drop audio/video here or click to browse</div>
                <div className="drop-hint">Drag and drop your recording</div>
                <div className="drop-accepts">Accepts: .mp4 .mov .webm .wav .m4a .mp3</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {error && <p className="form-error">{error}</p>}

      <button
        type="submit"
        className="submit-btn"
        disabled={loading || !pdfFile || !audioFile}
      >
        {loading ? <span className="spinner spinner--dark" /> : "Process Lecture"}
      </button>
    </form>
  );
}
