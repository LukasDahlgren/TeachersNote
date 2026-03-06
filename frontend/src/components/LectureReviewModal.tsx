import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { approveLecture, buildAssetUrl, getCourses, getLecture, rejectLecture } from "../api";
import type { CanonicalLectureKind, Course, LectureDetail, TeachersNoteSummary } from "../types";
import ConfirmDialog from "./ConfirmDialog";
import ResizableSplitPane, { NOTES_PRESENTATION_SPLIT_STORAGE_KEY } from "./ResizableSplitPane";
import SlideViewer from "./SlideViewer";
import TranscriptPanel from "./TranscriptPanel";
import "../LectureReviewModal.css";

interface Props {
  lecture: TeachersNoteSummary;
  onApproved: (id: number) => void;
  onRejected: (id: number) => void;
  onClose: () => void;
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return "Action failed.";
}

function parseLectureName(name: string): { courseid: string; kind: string; lecture: string; year: string } | null {
  const stem = name.trim();
  const match = /^([A-Za-z0-9-]+)-([A-Za-z0-9-]+)-(.+)-(\d{4})(?:-\d+)?$/.exec(stem);
  if (!match) return null;
  const [, courseid, kind, lecture, year] = match;
  return {
    courseid: courseid.trim().toUpperCase(),
    kind: kind.trim().toLowerCase(),
    lecture: lecture.trim(),
    year: year.trim(),
  };
}

function toCanonicalKind(value: string | null | undefined): CanonicalLectureKind {
  return (value || "").trim().toLowerCase() === "other" ? "other" : "lecture";
}

export default function LectureReviewModal({ lecture, onApproved, onRejected, onClose }: Props) {
  const [data, setData] = useState<LectureDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeSlide, setActiveSlide] = useState(0);
  const [actionInFlight, setActionInFlight] = useState<"approve" | "reject" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmRejectOpen, setConfirmRejectOpen] = useState(false);
  const [activeCourses, setActiveCourses] = useState<Course[]>([]);
  const [coursesLoading, setCoursesLoading] = useState(false);
  const [coursesError, setCoursesError] = useState<string | null>(null);
  const [courseid, setCourseid] = useState("");
  const [kind, setKind] = useState<CanonicalLectureKind>("lecture");
  const [lectureValue, setLectureValue] = useState("");
  const [year, setYear] = useState(new Date().getFullYear().toString());
  const [courseOpen, setCourseOpen] = useState(false);
  const [courseSearch, setCourseSearch] = useState("");
  const [kindOpen, setKindOpen] = useState(false);
  const coursePickerRef = useRef<HTMLDivElement>(null);
  const kindPickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const parsed = parseLectureName(lecture.name);
    setCourseid((lecture.course_id ?? parsed?.courseid ?? "").trim());
    setKind(toCanonicalKind(lecture.naming_kind ?? parsed?.kind ?? "lecture"));
    setLectureValue((lecture.naming_lecture ?? parsed?.lecture ?? "").trim());
    setYear((lecture.naming_year ?? parsed?.year ?? new Date().getFullYear().toString()).trim());
    setActionError(null);
  }, [lecture]);

  useEffect(() => {
    let cancelled = false;
    getLecture(lecture.id, { includeTranscript: true })
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(toErrorMessage(err));
      });
    return () => { cancelled = true; };
  }, [lecture.id]);

  useEffect(() => {
    let cancelled = false;
    setCoursesLoading(true);
    setCoursesError(null);
    getCourses()
      .then((courses) => {
        if (cancelled) return;
        const activeOnly = courses
          .filter((course) => course.is_active)
          .sort((a, b) => a.code.localeCompare(b.code, undefined, { sensitivity: "base" }));
        setActiveCourses(activeOnly);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCoursesError(toErrorMessage(err));
          setActiveCourses([]);
        }
      })
      .finally(() => {
        if (!cancelled) setCoursesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const hasSelectedCourse = useMemo(
    () => activeCourses.some((course) => course.code === courseid),
    [activeCourses, courseid],
  );

  useEffect(() => {
    if (coursesLoading || !courseid) return;
    if (!hasSelectedCourse) {
      setCourseid("");
    }
  }, [courseid, coursesLoading, hasSelectedCourse]);

  useEffect(() => {
    if (!courseOpen) return;
    function handleClick(e: MouseEvent) {
      if (coursePickerRef.current && !coursePickerRef.current.contains(e.target as Node)) {
        setCourseOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [courseOpen]);

  useEffect(() => {
    if (!kindOpen) return;
    function handleClick(e: MouseEvent) {
      if (kindPickerRef.current && !kindPickerRef.current.contains(e.target as Node)) {
        setKindOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [kindOpen]);

  const onPrev = useCallback(() => setActiveSlide((s) => Math.max(0, s - 1)), []);
  const onNext = useCallback(() => {
    if (!data) return;
    setActiveSlide((s) => Math.min(data.slides.length - 1, s + 1));
  }, [data]);

  async function handleApprove() {
    const nextCourseid = courseid.trim();
    const nextKind = kind;
    const nextLecture = lectureValue.trim();
    const nextYear = year.trim();
    if (!nextCourseid || !nextLecture || !nextYear) {
      setActionError("Fill in Course, Lecture, and Year before approving.");
      return;
    }
    if (!/^\d{4}$/.test(nextYear)) {
      setActionError("Year must be exactly 4 digits.");
      return;
    }

    setActionError(null);
    setActionInFlight("approve");
    try {
      await approveLecture(lecture.id, {
        courseid: nextCourseid,
        kind: nextKind,
        lecture: nextLecture,
        year: nextYear,
      });
      onApproved(lecture.id);
    } catch (err) {
      setActionError(toErrorMessage(err));
      setActionInFlight(null);
    }
  }

  async function handleReject() {
    setActionError(null);
    setActionInFlight("reject");
    try {
      await rejectLecture(lecture.id);
      onRejected(lecture.id);
    } catch (err) {
      setActionError(toErrorMessage(err));
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
        message="Reject and permanently delete this lecture?"
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
              disabled={actionInFlight !== null || data === null || coursesLoading}
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
        <div className="review-metadata">
          <div className="review-metadata-field">
            <span>Course</span>
            <div className="program-picker" ref={coursePickerRef}>
              <button
                type="button"
                className={`program-picker-trigger${courseOpen ? " program-picker-trigger--open" : ""}`}
                disabled={actionInFlight !== null || coursesLoading}
                onClick={() => { if (!coursesLoading) setCourseOpen((o) => !o); }}
              >
                <span className={`program-picker-trigger-text${!courseid ? " program-picker-trigger-text--placeholder" : ""}`}>
                  {coursesLoading
                    ? "Loading courses…"
                    : courseid
                      ? (() => { const c = activeCourses.find((x) => x.code === courseid); return c ? `${c.name} (${c.display_code || c.code})` : courseid; })()
                      : "Select active course"}
                </span>
                <span className="program-picker-trigger-chevron">▾</span>
              </button>
              {courseOpen && (
                <div className="program-picker-popover">
                  <div className="program-picker-search">
                    <input
                      className="program-picker-search-input"
                      type="text"
                      placeholder="Search courses…"
                      value={courseSearch}
                      onChange={(e) => setCourseSearch(e.target.value)}
                      autoFocus
                    />
                  </div>
                  {activeCourses
                    .filter((c) => {
                      const q = courseSearch.trim().toLowerCase();
                      return !q || c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q);
                    })
                    .map((course) => (
                      <div
                        key={course.id}
                        className={`program-picker-option${course.code === courseid ? " program-picker-option--active" : ""}`}
                        onClick={() => { setCourseid(course.code); setCourseOpen(false); setCourseSearch(""); }}
                      >
                        {course.name} ({course.display_code || course.code})
                      </div>
                    ))}
                  {activeCourses.filter((c) => {
                    const q = courseSearch.trim().toLowerCase();
                    return !q || c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q);
                  }).length === 0 && (
                    <div className="program-picker-empty">No courses found</div>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="review-metadata-field">
            <span>Kind</span>
            <div className="program-picker" ref={kindPickerRef}>
              <button
                type="button"
                className={`program-picker-trigger${kindOpen ? " program-picker-trigger--open" : ""}`}
                disabled={actionInFlight !== null}
                onClick={() => setKindOpen((o) => !o)}
              >
                <span className="program-picker-trigger-text">
                  {kind === "other" ? "Other" : "Lecture"}
                </span>
                <span className="program-picker-trigger-chevron">▾</span>
              </button>
              {kindOpen && (
                <div className="program-picker-popover">
                  {[{ value: "lecture", label: "Lecture" }, { value: "other", label: "Other" }].map((opt) => (
                    <div
                      key={opt.value}
                      className={`program-picker-option${kind === opt.value ? " program-picker-option--active" : ""}`}
                      onClick={() => { setKind(opt.value as CanonicalLectureKind); setKindOpen(false); }}
                    >
                      {opt.label}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          <label className="review-metadata-field">
            <span>Lecture</span>
            <input
              type="text"
              value={lectureValue}
              disabled={actionInFlight !== null}
              onChange={(event) => setLectureValue(event.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="review-metadata-field">
            <span>Year</span>
            <input
              type="text"
              value={year}
              disabled={actionInFlight !== null}
              onChange={(event) => setYear(event.target.value)}
              autoComplete="off"
              inputMode="numeric"
              pattern="[0-9]{4}"
              maxLength={4}
            />
          </label>
        </div>
        <div className="review-raw-metadata" aria-label="Uploaded naming">
          <p className="review-raw-metadata-title">Uploaded Naming (Raw)</p>
          <div className="review-raw-metadata-grid">
            <span><strong>Course:</strong> {lecture.upload_naming_raw?.courseid || "—"}</span>
            <span><strong>Kind:</strong> {lecture.upload_naming_raw?.kind || "—"}</span>
            <span><strong>Lecture:</strong> {lecture.upload_naming_raw?.lecture || "—"}</span>
            <span><strong>Year:</strong> {lecture.upload_naming_raw?.year || "—"}</span>
          </div>
        </div>
        {coursesError && (
          <div className="review-action-error">Failed to load active courses: {coursesError}</div>
        )}
        {actionError && <div className="review-action-error">{actionError}</div>}

        <div className="review-body">
          {!data && !loadError && (
            <div className="review-loading">Loading lecture…</div>
          )}
          {loadError && (
            <div className="review-error">{loadError}</div>
          )}
          {data && (
            <ResizableSplitPane
              className="review-results-body"
              storageKey={NOTES_PRESENTATION_SPLIT_STORAGE_KEY}
              left={(
                <SlideViewer
                  slideText={data.slides[activeSlide]?.text ?? ""}
                  slideNumber={activeSlide + 1}
                  total={data.slides.length}
                  onPrev={onPrev}
                  onNext={onNext}
                  pdfUrl={pdfUrl}
                />
              )}
              right={<TranscriptPanel segments={segments} enriched={enriched} />}
            />
          )}
        </div>
      </div>
    </div>
    </>
  );
}
