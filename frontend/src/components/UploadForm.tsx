import { useEffect, useMemo, useRef, useState } from "react";
import { getProfileCourseOptions } from "../api";
import {
  type Course,
  type ProfileCourseOptions,
  type UploadLectureNamingInput,
  type UploadRecordingInput,
} from "../types";

interface ConsoleEntry {
  id: number;
  message: string;
  done?: boolean;
}

interface Props {
  onSubmit: (pdf: File, recording: UploadRecordingInput, naming: UploadLectureNamingInput) => void;
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
const URL_RECORDING_ENABLED = false;

interface ProgramCourseGroupOption {
  programId: number;
  programLabel: string;
  courses: Course[];
}

function normalizeCourseCode(value: string): string {
  return value.trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function studentCourseCode(course: Course): string {
  return course.display_code?.trim() || course.code;
}

function dedupeCoursesByCode(courses: Course[]): Course[] {
  const byCode = new Map<string, Course>();
  for (const course of courses) {
    const key = normalizeCourseCode(course.code);
    if (!key || byCode.has(key)) continue;
    byCode.set(key, course);
  }
  return [...byCode.values()].sort((a, b) => a.code.localeCompare(b.code, undefined, { sensitivity: "base" }));
}

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
  const [recordingSource, setRecordingSource] = useState<"file" | "url">("file");
  const [audioUrl, setAudioUrl] = useState("");
  const [courseid, setCourseid] = useState("");
  const [isCoursePickerOpen, setIsCoursePickerOpen] = useState(false);
  const [expandedProgramIds, setExpandedProgramIds] = useState<number[]>([]);
  const [profileOptions, setProfileOptions] = useState<ProfileCourseOptions | null>(null);
  const [courseOptionsLoading, setCourseOptionsLoading] = useState(true);
  const [courseOptionsError, setCourseOptionsError] = useState("");
  const [kind, setKind] = useState("lecture");
  const [lecture, setLecture] = useState("");
  const [year, setYear] = useState("");
  const [pdfDragOver, setPdfDragOver] = useState(false);
  const [audioDragOver, setAudioDragOver] = useState(false);
  const [error, setError] = useState("");
  const [showHowItWorks, setShowHowItWorks] = useState(false);
  const coursePickerRef = useRef<HTMLDivElement>(null);
  const pdfInputRef = useRef<HTMLInputElement>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);
  const effectiveRecordingSource: "file" | "url" = URL_RECORDING_ENABLED ? recordingSource : "file";

  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [consoleEntries]);

  useEffect(() => {
    let cancelled = false;

    async function loadCourseOptions() {
      setCourseOptionsLoading(true);
      setCourseOptionsError("");
      try {
        const nextOptions = await getProfileCourseOptions();
        if (cancelled) return;
        setProfileOptions(nextOptions);
      } catch (err) {
        if (cancelled) return;
        setProfileOptions(null);
        setCourseOptionsError(err instanceof Error ? err.message : "Failed to load course options.");
      } finally {
        if (!cancelled) {
          setCourseOptionsLoading(false);
        }
      }
    }

    void loadCourseOptions();
    return () => {
      cancelled = true;
    };
  }, []);

  const programCourseGroups = useMemo<ProgramCourseGroupOption[]>(() => {
    const fromApi = profileOptions?.program_course_groups ?? [];
    const allCourses = dedupeCoursesByCode(profileOptions?.all_courses ?? []);
    if (fromApi.length > 0) {
      const grouped: ProgramCourseGroupOption[] = [];
      const groupedCodes = new Set<string>();
      for (const group of fromApi) {
        const courses = dedupeCoursesByCode(group.courses ?? []);
        for (const course of courses) {
          groupedCodes.add(normalizeCourseCode(course.code));
        }
        grouped.push({
          programId: group.program.id,
          programLabel: `${group.program.name} (${group.program.code})`,
          courses,
        });
      }

      const ungrouped = allCourses.filter((course) => !groupedCodes.has(normalizeCourseCode(course.code)));
      if (ungrouped.length > 0) {
        grouped.push({
          programId: -1,
          programLabel: "Other active courses",
          courses: ungrouped,
        });
      }
      return grouped;
    }

    if (allCourses.length === 0) {
      return [];
    }
    return [
      {
        programId: -1,
        programLabel: "All courses",
        courses: allCourses,
      },
    ];
  }, [profileOptions]);

  useEffect(() => {
    if (!courseid) return;
    const exists = programCourseGroups.some((group) => group.courses.some((course) => course.code === courseid));
    if (!exists) {
      setCourseid("");
    }
  }, [courseid, programCourseGroups]);

  const selectedCourse = useMemo(() => {
    for (const group of programCourseGroups) {
      const match = group.courses.find((course) => course.code === courseid);
      if (match) {
        return { group, course: match };
      }
    }
    return null;
  }, [courseid, programCourseGroups]);

  useEffect(() => {
    if (!isCoursePickerOpen || courseOptionsLoading || programCourseGroups.length === 0) return;

    const validProgramIds = new Set(programCourseGroups.map((group) => group.programId));
    setExpandedProgramIds((prev) => {
      const filtered = prev.filter((programId) => validProgramIds.has(programId));
      if (filtered.length > 0) return filtered;
      if (selectedCourse) return [selectedCourse.group.programId];
      return [];
    });
  }, [courseOptionsLoading, isCoursePickerOpen, programCourseGroups, selectedCourse]);

  useEffect(() => {
    if (!isCoursePickerOpen) return;

    function handleDocumentClick(event: MouseEvent) {
      if (!coursePickerRef.current?.contains(event.target as Node)) {
        setIsCoursePickerOpen(false);
      }
    }

    document.addEventListener("mousedown", handleDocumentClick);
    return () => {
      document.removeEventListener("mousedown", handleDocumentClick);
    };
  }, [isCoursePickerOpen]);

  useEffect(() => {
    if (loading || courseOptionsLoading || programCourseGroups.length === 0) {
      setIsCoursePickerOpen(false);
    }
  }, [courseOptionsLoading, loading, programCourseGroups]);

  function toggleProgramGroup(programId: number) {
    setExpandedProgramIds((prev) => (prev.includes(programId) ? [] : [programId]));
  }

  function handleSelectCourse(code: string) {
    setCourseid(code);
    setError("");
    setIsCoursePickerOpen(false);
  }

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
    if (!pdfFile) {
      setError("Please select a PDF file for slides.");
      return;
    }

    let recording: UploadRecordingInput | null = null;
    if (effectiveRecordingSource === "file") {
      if (!audioFile) {
        setError("Please select an audio or video file.");
        return;
      }
      recording = { type: "file", file: audioFile };
    } else {
      const nextAudioUrl = audioUrl.trim();
      if (!nextAudioUrl) {
        setError("Please provide a recording URL.");
        return;
      }
      try {
        const parsed = new URL(nextAudioUrl);
        if (parsed.protocol !== "https:") {
          setError("Recording URL must use HTTPS.");
          return;
        }
      } catch {
        setError("Please provide a valid recording URL.");
        return;
      }
      recording = { type: "url", url: nextAudioUrl };
    }

    const nextCourseid = courseid.trim();
    const nextKind = kind.trim() || "lecture";
    const nextLecture = lecture.trim();
    const nextYear = year.trim();
    if (!nextCourseid || !nextLecture || !nextYear) {
      setError("Please fill in Course, Lecture, and Year.");
      return;
    }
    if (!/^\d{4}$/.test(nextYear)) {
      setError("Year must be exactly 4 digits.");
      return;
    }

    setError("");
    onSubmit(pdfFile, recording, {
      courseid: nextCourseid,
      kind: nextKind,
      lecture: nextLecture,
      year: nextYear,
    });
  }

  return (
    <form className={`upload-form${loading ? " upload-form--loading" : ""}`} onSubmit={handleSubmit}>
      <h1 className="form-title">TeachersNote</h1>
      <p className="form-subtitle">
        Upload lecture slides (PDF) and add a recording file or direct URL to generate an aligned transcript.
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
              Upload your lecture slides (PDF) and recording. Our system extracts the slide content, transcribes the
              audio, and aligns each transcript segment to the corresponding slide. Then it generates rich notes and
              takeaways for each slide.
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

      <div className="naming-fields">
        <div className="naming-field naming-field--course">
          <label className="drop-zone-label" htmlFor="courseid-input">Course</label>
          <div className="course-picker" ref={coursePickerRef}>
            <button
              id="courseid-input"
              type="button"
              className={`course-picker-trigger${isCoursePickerOpen ? " course-picker-trigger--open" : ""}`}
              disabled={loading || courseOptionsLoading || programCourseGroups.length === 0}
              aria-haspopup="listbox"
              aria-expanded={isCoursePickerOpen}
              aria-controls="course-picker-menu"
              onClick={() => setIsCoursePickerOpen((prev) => !prev)}
            >
              <span className={`course-picker-trigger-text${selectedCourse ? "" : " course-picker-trigger-text--placeholder"}`}>
                {selectedCourse
                  ? `${selectedCourse.course.name} (${studentCourseCode(selectedCourse.course)})`
                  : (courseOptionsLoading ? "Loading courses..." : "Select a course")}
              </span>
              <span className="course-picker-trigger-chevron">▾</span>
            </button>

            {isCoursePickerOpen && !courseOptionsLoading && programCourseGroups.length > 0 && (
              <div id="course-picker-menu" className="course-picker-popover" role="listbox" aria-label="Course picker">
                {programCourseGroups.map((group) => {
                  const isExpanded = expandedProgramIds.includes(group.programId);
                  return (
                    <div key={group.programId} className="course-picker-group">
                      <button
                        type="button"
                        className={`course-picker-group-btn${isExpanded ? " course-picker-group-btn--open" : ""}`}
                        onClick={() => toggleProgramGroup(group.programId)}
                        aria-expanded={isExpanded}
                      >
                        <span className="course-picker-group-label">{group.programLabel}</span>
                        <span className="course-picker-group-chevron">▾</span>
                      </button>

                      {isExpanded && (
                        <div className="course-picker-course-list">
                          {group.courses.length === 0 && (
                            <p className="course-picker-empty">No courses mapped in this program.</p>
                          )}
                          {group.courses.map((course) => (
                            <button
                              key={`${group.programId}-${course.id}`}
                              type="button"
                              className={`course-picker-course-btn${course.code === courseid ? " course-picker-course-btn--active" : ""}`}
                              onClick={() => handleSelectCourse(course.code)}
                            >
                              <span className="course-picker-course-name">{course.name}</span>
                              <span className="course-picker-course-code">{studentCourseCode(course)}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          {!courseOptionsLoading && programCourseGroups.length === 0 && !courseOptionsError && (
            <p className="naming-field-hint naming-field-hint--error">
              No catalog courses are available yet. Run catalog sync and refresh this page.
            </p>
          )}
          {courseOptionsError && (
            <p className="naming-field-hint naming-field-hint--error">{courseOptionsError}</p>
          )}
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

      <div className="recording-source">
        <div className="drop-zone-label">Recording Source</div>
        <div className="recording-source-options">
          <label className="recording-source-option">
            <input
              type="radio"
              name="recording-source"
              value="file"
              checked={recordingSource === "file"}
              disabled={loading}
              onChange={() => {
                setError("");
                setRecordingSource("file");
              }}
            />
            Upload File
          </label>
          <label className={`recording-source-option${URL_RECORDING_ENABLED ? "" : " recording-source-option--disabled"}`}>
            <input
              type="radio"
              name="recording-source"
              value="url"
              checked={recordingSource === "url"}
              disabled={loading || !URL_RECORDING_ENABLED}
              onChange={() => {
                if (!URL_RECORDING_ENABLED) return;
                setError("");
                setRecordingSource("url");
              }}
            />
            Paste URL {!URL_RECORDING_ENABLED ? "(Unavailable)" : ""}
          </label>
        </div>
      </div>

      {effectiveRecordingSource === "file" ? (
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
      ) : (
        <div className="drop-zone-wrapper">
          <label className="drop-zone-label" htmlFor="audio-url-input">Recording URL</label>
          <input
            id="audio-url-input"
            className="naming-input recording-url-input"
            type="url"
            value={audioUrl}
            disabled={loading}
            autoComplete="off"
            onChange={(e) => {
              setAudioUrl(e.target.value);
              setError("");
            }}
            placeholder="https://example.org/lecture.mp4?token=..."
          />
          <div className="recording-url-hint">Use a direct media file URL (.mp4, .mov, .webm, .wav, .m4a, .mp3).</div>
        </div>
      )}

      {error && <p className="form-error">{error}</p>}

      <div className="submit-actions">
        <button
          type="submit"
          className="submit-btn"
          disabled={
            loading
            || courseOptionsLoading
            || !pdfFile
            || (effectiveRecordingSource === "file" ? !audioFile : !audioUrl.trim())
            || !courseid.trim()
            || !lecture.trim()
            || !year.trim()
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
