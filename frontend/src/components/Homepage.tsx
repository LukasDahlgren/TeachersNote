import { useEffect, useMemo, useState } from "react";
import { Document, Page } from "react-pdf";
import {
  buildAssetUrl,
  getProfileCourseOptions,
  updateProfileProgram,
} from "../api";
import ProgramPicker from "./ProgramPicker";
import type {
  TeachersNoteSummary,
  ProfileCourseOptions,
  StudentProfile,
} from "../types";
import { ensurePdfWorker } from "../pdfWorker";

interface HomepageProps {
  savedLectures: TeachersNoteSummary[];
  allLectures: TeachersNoteSummary[];
  loading: boolean;
  profile: StudentProfile | null;
  profileLoading: boolean;
  onProfileChange: (profile: StudentProfile) => void;
  onOpenLecture: (id: number) => void;
}

interface LectureNameParts {
  courseId: string;
  lectureLabel: string;
  displayName: string;
  kind: string;
  number: string;
}

interface HomepageLectureItem {
  lecture: TeachersNoteSummary;
  courseId: string;
  courseDisplay: string;
  courseCodeNormalized: string;
  lectureLabel: string;
  displayName: string;
  kind: string;
  number: string;
  createdAtMs: number;
}

function stripExtension(value: string): string {
  return value.replace(/\.[^./\\]+$/, "");
}

function splitLectureName(name: string): LectureNameParts {
  const cleanedName = stripExtension(name).replace(/\s+/g, " ").trim();
  if (!cleanedName) {
    return { courseId: "Lecture", lectureLabel: "Lecture", displayName: "Lecture", kind: "", number: "" };
  }

  const courseId = cleanedName.split(/[-\s_]+/).filter(Boolean)[0] ?? cleanedName;
  let lectureLabel = cleanedName.slice(courseId.length).replace(/^[\s_-]+/, "").trim();
  if (!lectureLabel) lectureLabel = cleanedName;

  const parts = lectureLabel.split(/[-\s_]+/).filter(Boolean);
  let displayName = lectureLabel;
  let kind = "";
  let number = "";

  if (parts.length >= 2) {
    const lastPart = parts[parts.length - 1];
    if (/^\d+$/.test(lastPart)) {
      number = lastPart;
      const potentialKind = parts[parts.length - 2];
      if (/^[a-z]/i.test(potentialKind) && !/^\d+$/.test(potentialKind)) {
        kind = potentialKind;
        displayName = parts.slice(0, parts.length - 2).join(" ");
        if (!displayName) { displayName = potentialKind; kind = ""; }
      } else {
        displayName = parts.slice(0, parts.length - 1).join(" ");
      }
    }
  }

  return { courseId, lectureLabel, displayName, kind, number };
}

function normalizeQuery(value: string): string {
  return value.trim().toLowerCase();
}

function normalizeCourseCode(value: string | null | undefined): string {
  return (value ?? "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
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

ensurePdfWorker();

export default function Homepage({
  savedLectures,
  allLectures,
  loading,
  profile,
  profileLoading,
  onProfileChange,
  onOpenLecture,
}: HomepageProps) {
  const [searchQuery, setSearchQuery] = useState("");

  const [profileOptions, setProfileOptions] = useState<ProfileCourseOptions | null>(null);
  const [profileOptionsLoading, setProfileOptionsLoading] = useState(true);
  const [profileOptionsError, setProfileOptionsError] = useState<string | null>(null);
  const [programSavePending, setProgramSavePending] = useState(false);
  const [profileSaveBanner, setProfileSaveBanner] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);
  const [isProgramMenuOpen, setIsProgramMenuOpen] = useState(false);
  const [draftProgramId, setDraftProgramId] = useState<number | null>(null);

  useEffect(() => {
    setDraftProgramId(profile?.program?.id ?? null);
  }, [profile]);

  async function loadProfileOptions() {
    setProfileOptionsLoading(true);
    setProfileOptionsError(null);
    try {
      const options = await getProfileCourseOptions();
      setProfileOptions(options);
    } catch (err) {
      setProfileOptionsError(err instanceof Error ? err.message : "Failed to load profile options.");
    } finally {
      setProfileOptionsLoading(false);
    }
  }

  useEffect(() => { void loadProfileOptions(); }, []);

  useEffect(() => {
    if (!profile?.program) setIsProgramMenuOpen(false);
  }, [profile?.program]);

  const currentProgram = profile?.program ?? null;
  const programCourses = useMemo(() => profileOptions?.program_courses ?? [], [profileOptions?.program_courses]);

  const toLectureItem = (lecture: TeachersNoteSummary): HomepageLectureItem => {
    const parsed = splitLectureName(lecture.name);
    const derivedCourseId = lecture.course_id?.trim() || parsed.courseId;
    const derivedCourseDisplay = lecture.course_display?.trim() || derivedCourseId;
    return {
      lecture,
      courseId: derivedCourseId,
      courseDisplay: derivedCourseDisplay,
      courseCodeNormalized: normalizeCourseCode(derivedCourseId || parsed.courseId),
      lectureLabel: parsed.lectureLabel,
      displayName: parsed.displayName,
      kind: parsed.kind,
      number: parsed.number,
      createdAtMs: Date.parse(lecture.created_at) || 0,
    };
  };

  const mySavedActiveLectures = useMemo(
    () => savedLectures.filter((l) => !l.is_archived).map(toLectureItem),
    [savedLectures],
  );

  const acceptedAllLectures = useMemo(
    () => allLectures.filter((l) => !l.is_archived).map(toLectureItem),
    [allLectures],
  );

  const programCourseCodeSet = useMemo(() => new Set(
    programCourses.map((c) => normalizeCourseCode(c.code)).filter((code) => code.length > 0),
  ), [programCourses]);

  const totalMyProgramLectures = useMemo(() => {
    if (!currentProgram || programCourseCodeSet.size === 0) return [];
    return sortLectureItems(
      acceptedAllLectures.filter((l) => programCourseCodeSet.has(l.courseCodeNormalized)),
    );
  }, [acceptedAllLectures, currentProgram, programCourseCodeSet]);

  const normalizedQuery = normalizeQuery(searchQuery);

  const filteredSavedLectures = useMemo(() => {
    if (!normalizedQuery) return mySavedActiveLectures;
    return mySavedActiveLectures.filter((item) => lectureMatchesQuery(item, normalizedQuery));
  }, [mySavedActiveLectures, normalizedQuery]);

  const filteredMyProgramLectures = useMemo(() => {
    if (!normalizedQuery) return totalMyProgramLectures;
    return totalMyProgramLectures.filter((item) => lectureMatchesQuery(item, normalizedQuery));
  }, [totalMyProgramLectures, normalizedQuery]);

  const filteredAllLectures = useMemo(() => {
    if (!normalizedQuery) return acceptedAllLectures;
    return acceptedAllLectures.filter((item) => lectureMatchesQuery(item, normalizedQuery));
  }, [acceptedAllLectures, normalizedQuery]);

  async function handleSaveProgram() {
    setProgramSavePending(true);
    setProfileSaveBanner(null);
    try {
      const updatedProfile = await updateProfileProgram(draftProgramId);
      onProfileChange(updatedProfile);
      await loadProfileOptions();
      setProfileSaveBanner({ kind: "success", text: "Program saved." });
      setIsProgramMenuOpen(false);
    } catch (err) {
      setProfileSaveBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to save program.",
      });
    } finally {
      setProgramSavePending(false);
    }
  }

  const programOptions = profileOptions?.programs ?? [];

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

  return (
    <section className="homepage homepage-v2 app-surface app-surface--stagger">

      {/* Header: search + program badge */}
      <div className="homepage-v2-header app-surface-item app-surface-item--1">
        <input
          type="search"
          className="homepage-search-input"
          placeholder="Search lectures"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
        {currentProgram && (
          <div className="homepage-v2-program-badge">
            <div className="homepage-v2-program-badge-text">
              <span className="homepage-v2-program-badge-label">Program</span>
              <span className="homepage-v2-program-badge-value">{currentProgram.code} – {currentProgram.name}</span>
            </div>
            <button
              type="button"
              className="homepage-v2-program-change-btn"
              onClick={() => setIsProgramMenuOpen((prev) => !prev)}
              disabled={programSavePending}
            >
              {isProgramMenuOpen ? "Close" : "Change"}
            </button>
            {isProgramMenuOpen && (
              <div className="homepage-program-popup" role="dialog" aria-label="Change program">
                {profileOptionsError && <p className="homepage-profile-error">{profileOptionsError}</p>}
                <div className="homepage-profile-field">
                  <label htmlFor="profile-program-popup">Program</label>
                  <ProgramPicker
                    id="profile-program-popup"
                    value={draftProgramId}
                    programs={programOptions}
                    onChange={setDraftProgramId}
                    disabled={profileOptionsLoading || programSavePending}
                    showAllOption
                    showAllLabel="Show all"
                    placeholder="Select a program"
                  />
                </div>
                <div className="homepage-program-popup-actions">
                  <button
                    type="button"
                    className="homepage-program-popup-cancel-btn"
                    onClick={() => setIsProgramMenuOpen(false)}
                    disabled={programSavePending}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="homepage-profile-save-btn"
                    onClick={() => void handleSaveProgram()}
                    disabled={programSavePending || profileOptionsLoading}
                  >
                    {programSavePending ? "Saving..." : "Save program"}
                  </button>
                </div>
                {profileSaveBanner && (
                  <p className={`homepage-profile-banner homepage-profile-banner--${profileSaveBanner.kind}`}>
                    {profileSaveBanner.text}
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Program setup — shown when no program configured */}
      {!currentProgram && !profileLoading && (
        <section className="homepage-profile-section app-surface-item app-surface-item--2">
          <div className="homepage-profile-setup-card">
            <h3>Select your program</h3>
            <p>Configure your program to unlock your program courses on the homepage.</p>
          </div>
          <div className="homepage-profile-editor">
            <div className="homepage-profile-editor-header">
              <h3>My study profile</h3>
              {profileOptionsLoading && <span className="homepage-profile-meta">Loading options...</span>}
            </div>
            {profileOptionsError && <p className="homepage-profile-error">{profileOptionsError}</p>}
            <div className="homepage-profile-field">
              <label htmlFor="profile-program">Program</label>
              <ProgramPicker
                id="profile-program"
                value={draftProgramId}
                programs={programOptions}
                onChange={setDraftProgramId}
                disabled={profileOptionsLoading || programSavePending}
                showAllOption
                showAllLabel="Show all"
                placeholder="Select a program"
              />
              <button
                type="button"
                className="homepage-profile-save-btn"
                onClick={() => void handleSaveProgram()}
                disabled={programSavePending || profileOptionsLoading}
              >
                {programSavePending ? "Saving..." : "Save program"}
              </button>
            </div>
            {profileSaveBanner && (
              <p className={`homepage-profile-banner homepage-profile-banner--${profileSaveBanner.kind}`}>
                {profileSaveBanner.text}
              </p>
            )}
          </div>
        </section>
      )}

      {loading && (
        <div className="homepage-loading app-surface-item app-surface-item--2">
          <span className="spinner spinner--dark-sm" />
        </div>
      )}

      {/* Saved lectures */}
      {!loading && mySavedActiveLectures.length > 0 && (
        <div className="homepage-v2-section app-surface-item app-surface-item--2">
          <h2 className="homepage-v2-section-heading">Saved</h2>
          <div className="homepage-v2-grid">
            {filteredSavedLectures.map((item) => renderLectureCard(item))}
            {filteredSavedLectures.length === 0 && (
              <p className="homepage-v2-empty">No saved lectures match your search.</p>
            )}
          </div>
        </div>
      )}

      {/* My Program lectures */}
      {!loading && currentProgram && totalMyProgramLectures.length > 0 && (
        <div className="homepage-v2-section app-surface-item app-surface-item--3">
          <h2 className="homepage-v2-section-heading">My Program</h2>
          <div className="homepage-v2-grid">
            {filteredMyProgramLectures.map((item) => renderLectureCard(item))}
            {filteredMyProgramLectures.length === 0 && (
              <p className="homepage-v2-empty">No program lectures match your search.</p>
            )}
          </div>
        </div>
      )}

      {/* All lectures */}
      {!loading && (
        <div className="homepage-v2-section app-surface-item app-surface-item--4">
          <h2 className="homepage-v2-section-heading">All</h2>
          <div className="homepage-v2-grid">
            {acceptedAllLectures.length === 0 && (
              <p className="homepage-v2-empty">No lectures are available yet.</p>
            )}
            {acceptedAllLectures.length > 0 && filteredAllLectures.length === 0 && (
              <p className="homepage-v2-empty">No lectures match your search.</p>
            )}
            {filteredAllLectures.map((item) => renderLectureCard(item))}
          </div>
        </div>
      )}

    </section>
  );
}
