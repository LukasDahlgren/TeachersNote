import { useMemo, useState, type ReactNode } from "react";
import { Document, Page } from "react-pdf";
import { buildAssetUrl } from "../api";
import type { TeachersNoteSummary } from "../types";
import { ensurePdfWorker } from "../pdfWorker";
import { splitLectureName } from "../utils/lectureNaming";

interface HomepageProps {
  savedLectures: TeachersNoteSummary[];
  allLectures: TeachersNoteSummary[];
  loading: boolean;
  onOpenLecture: (id: number) => void;
}

interface HomepageLectureItem {
  lecture: TeachersNoteSummary;
  courseId: string;
  courseDisplay: string;
  lectureLabel: string;
  displayName: string;
  kind: string;
  number: string;
  createdAtMs: number;
}

type HomepageSectionKey = "saved" | "all";

interface HomepageSectionState {
  saved: boolean;
  all: boolean;
}

const HOMEPAGE_SECTION_STORAGE_KEY = "teachers-note.homepage-sections";

function normalizeQuery(value: string): string {
  return value.trim().toLowerCase();
}

function lectureMatchesQuery(item: HomepageLectureItem, normalizedQuery: string): boolean {
  if (!normalizedQuery) return true;
  return `${item.lecture.name} ${item.courseId} ${item.courseDisplay} ${item.lectureLabel}`
    .toLowerCase()
    .includes(normalizedQuery);
}

function sortLectureItems(lectures: HomepageLectureItem[]): HomepageLectureItem[] {
  return [...lectures].sort((a, b) => {
    if (b.createdAtMs !== a.createdAtMs) return b.createdAtMs - a.createdAtMs;
    return a.lecture.name.localeCompare(b.lecture.name, undefined, { sensitivity: "base" });
  });
}

function readStoredHomepageSectionState(): HomepageSectionState {
  const fallback: HomepageSectionState = { saved: true, all: true };
  if (typeof window === "undefined") return fallback;

  try {
    const raw = window.localStorage.getItem(HOMEPAGE_SECTION_STORAGE_KEY);
    if (!raw) return fallback;

    const parsed = JSON.parse(raw) as Partial<Record<string, unknown>> | null;
    if (!parsed || typeof parsed !== "object") return fallback;

    return {
      saved: typeof parsed.saved === "boolean" ? parsed.saved : fallback.saved,
      all: typeof parsed.all === "boolean" ? parsed.all : fallback.all,
    };
  } catch {
    return fallback;
  }
}

ensurePdfWorker();

export default function Homepage({
  savedLectures,
  allLectures,
  loading,
  onOpenLecture,
}: HomepageProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [sectionState, setSectionState] = useState<HomepageSectionState>(() => readStoredHomepageSectionState());

  const toLectureItem = (lecture: TeachersNoteSummary): HomepageLectureItem => {
    const parsed = splitLectureName(lecture.name);
    const derivedCourseId = lecture.course_id?.trim() || parsed.courseId;
    const derivedCourseDisplay = lecture.course_display?.trim() || derivedCourseId;
    return {
      lecture,
      courseId: derivedCourseId,
      courseDisplay: derivedCourseDisplay,
      lectureLabel: parsed.lectureLabel,
      displayName: parsed.displayName,
      kind: parsed.kind,
      number: parsed.number,
      createdAtMs: Date.parse(lecture.created_at) || 0,
    };
  };

  const mySavedActiveLectures = useMemo(
    () => sortLectureItems(savedLectures.filter((lecture) => !lecture.is_archived).map(toLectureItem)),
    [savedLectures],
  );

  const acceptedAllLectures = useMemo(
    () => sortLectureItems(allLectures.filter((lecture) => !lecture.is_archived).map(toLectureItem)),
    [allLectures],
  );

  const normalizedQuery = normalizeQuery(searchQuery);

  const filteredSavedLectures = useMemo(() => {
    if (!normalizedQuery) return mySavedActiveLectures;
    return mySavedActiveLectures.filter((item) => lectureMatchesQuery(item, normalizedQuery));
  }, [mySavedActiveLectures, normalizedQuery]);

  const filteredAllLectures = useMemo(() => {
    if (!normalizedQuery) return acceptedAllLectures;
    return acceptedAllLectures.filter((item) => lectureMatchesQuery(item, normalizedQuery));
  }, [acceptedAllLectures, normalizedQuery]);

  function toggleSection(section: HomepageSectionKey) {
    setSectionState((prev) => {
      const next = { ...prev, [section]: !prev[section] };
      try {
        window.localStorage.setItem(HOMEPAGE_SECTION_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Ignore storage errors so the homepage still works in restricted environments.
      }
      return next;
    });
  }

  function renderLectureCard(item: HomepageLectureItem) {
    const { lecture, courseDisplay, displayName, kind, number } = item;
    const pdfUrl = buildAssetUrl(lecture.pdf_url);
    const titleParts = [displayName];
    if (kind) titleParts.push(kind);
    if (number) titleParts.push(number);
    const mainTitle = titleParts.join(" - ");

    return (
      <button
        key={lecture.id}
        type="button"
        className="homepage-v2-card"
        onClick={() => onOpenLecture(lecture.id)}
      >
        <div className="homepage-v2-card-preview">
          {pdfUrl ? (
            <Document
              file={pdfUrl}
              loading={<div className="homepage-preview-fallback">Loading...</div>}
              error={<div className="homepage-preview-fallback">No preview</div>}
            >
              <Page pageNumber={1} width={280} renderTextLayer={false} renderAnnotationLayer={false} />
            </Document>
          ) : (
            <div className="homepage-preview-fallback">No preview</div>
          )}
        </div>
        <div className="homepage-v2-card-meta">
          <span className="homepage-v2-course-tag">{courseDisplay}</span>
          <p className="homepage-v2-card-title">{mainTitle}</p>
        </div>
      </button>
    );
  }

  function renderSection(
    section: HomepageSectionKey,
    title: string,
    count: number,
    surfaceClassName: string,
    children: ReactNode,
  ) {
    const isExpanded = sectionState[section];
    const contentId = `homepage-v2-section-${section}`;

    return (
      <section className={`homepage-v2-section ${surfaceClassName}`}>
        <div className="homepage-v2-section-header">
          <button
            type="button"
            className="homepage-v2-section-toggle"
            onClick={() => toggleSection(section)}
            aria-expanded={isExpanded}
            aria-controls={contentId}
          >
            <span className="homepage-v2-section-heading">{title}</span>
            <span className="homepage-v2-section-header-meta">
              <span className="homepage-v2-section-count">{count}</span>
              <span
                className={`homepage-v2-section-chevron${isExpanded ? " homepage-v2-section-chevron--expanded" : ""}`}
                aria-hidden="true"
              >
                ▾
              </span>
            </span>
          </button>
        </div>
        <div id={contentId} className="homepage-v2-section-body" hidden={!isExpanded}>
          {children}
        </div>
      </section>
    );
  }

  return (
    <section className="homepage homepage-v2 app-surface app-surface--stagger">
      <div className="homepage-v2-header app-surface-item app-surface-item--1">
        <input
          type="search"
          className="homepage-search-input"
          placeholder="Search lectures"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
      </div>

      {loading && (
        <div className="homepage-loading app-surface-item app-surface-item--2">
          <span className="spinner spinner--dark-sm" />
        </div>
      )}

      {!loading && mySavedActiveLectures.length > 0 && (
        renderSection(
          "saved",
          "Saved",
          filteredSavedLectures.length,
          "app-surface-item app-surface-item--2",
          <div className="homepage-v2-grid">
            {filteredSavedLectures.map((item) => renderLectureCard(item))}
            {filteredSavedLectures.length === 0 && (
              <p className="homepage-v2-empty">No saved lectures match your search.</p>
            )}
          </div>,
        )
      )}

      {!loading && (
        renderSection(
          "all",
          "All",
          filteredAllLectures.length,
          "app-surface-item app-surface-item--3",
          <div className="homepage-v2-grid">
            {acceptedAllLectures.length === 0 && (
              <p className="homepage-v2-empty">No lectures are available yet.</p>
            )}
            {acceptedAllLectures.length > 0 && filteredAllLectures.length === 0 && (
              <p className="homepage-v2-empty">No lectures match your search.</p>
            )}
            {filteredAllLectures.map((item) => renderLectureCard(item))}
          </div>,
        )
      )}
    </section>
  );
}
