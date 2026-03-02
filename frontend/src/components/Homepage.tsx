import { useEffect, useMemo, useState } from "react";
import { Document, Page } from "react-pdf";
import {
  buildAssetUrl,
  getProfileCourseOptions,
  updateProfileProgram,
} from "../api";
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
}

interface HomepageLectureItem {
  lecture: TeachersNoteSummary;
  courseId: string;
  courseCodeNormalized: string;
  lectureLabel: string;
  createdAtMs: number;
}

function stripExtension(value: string): string {
  return value.replace(/\.[^./\\]+$/, "");
}

function splitLectureName(name: string): LectureNameParts {
  const cleanedName = stripExtension(name).replace(/\s+/g, " ").trim();
  if (!cleanedName) {
    return { courseId: "Lecture", lectureLabel: "Lecture" };
  }

  const courseId = cleanedName.split(/[-\s_]+/).filter(Boolean)[0] ?? cleanedName;
  let lectureLabel = cleanedName.slice(courseId.length).replace(/^[\s_-]+/, "").trim();
  if (!lectureLabel) {
    lectureLabel = cleanedName;
  }

  return { courseId, lectureLabel };
}

function normalizeQuery(value: string): string {
  return value.trim().toLowerCase();
}

function normalizeCourseCode(value: string | null | undefined): string {
  return (value ?? "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function lectureMatchesQuery(item: HomepageLectureItem, normalizedQuery: string): boolean {
  if (!normalizedQuery) return true;
  return `${item.lecture.name} ${item.courseId} ${item.lectureLabel}`
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
  const [expandedCourseIds, setExpandedCourseIds] = useState<string[]>([]);

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

  useEffect(() => {
    void loadProfileOptions();
  }, []);

  const currentProgram = profile?.program ?? null;
  const programCourses = useMemo(
    () => profileOptions?.program_courses ?? [],
    [profileOptions?.program_courses],
  );

  useEffect(() => {
    if (!currentProgram) {
      setIsProgramMenuOpen(false);
    }
  }, [currentProgram]);

  const toLectureItem = (lecture: TeachersNoteSummary): HomepageLectureItem => {
    const parsed = splitLectureName(lecture.name);
    const derivedCourseId = lecture.course_id?.trim() || parsed.courseId;
    return {
      lecture,
      courseId: derivedCourseId,
      courseCodeNormalized: normalizeCourseCode(derivedCourseId || parsed.courseId),
      lectureLabel: parsed.lectureLabel,
      createdAtMs: Date.parse(lecture.created_at) || 0,
    };
  };

  const mySavedActiveLectures = useMemo(
    () => savedLectures
      .filter((lecture) => !lecture.is_archived)
      .map(toLectureItem),
    [savedLectures],
  );

  const acceptedAllLectures = useMemo(
    () => allLectures
      .filter((lecture) => !lecture.is_archived)
      .map(toLectureItem),
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

  const groupedAllLectures = (() => {
    const byCourse = new Map<string, HomepageLectureItem[]>();
    for (const lecture of filteredAllLectures) {
      const existing = byCourse.get(lecture.courseId);
      if (existing) {
        existing.push(lecture);
      } else {
        byCourse.set(lecture.courseId, [lecture]);
      }
    }

    return [...byCourse.entries()]
      .sort(([courseA], [courseB]) => courseA.localeCompare(courseB, undefined, { sensitivity: "base" }))
      .map(([courseId, lectures]) => ({
        courseId,
        lectures: sortLectureItems(lectures),
      }));
  })();

  const programCourseCodeSet = useMemo(() => {
    return new Set(
      programCourses
        .map((course) => normalizeCourseCode(course.code))
        .filter((code) => code.length > 0),
    );
  }, [programCourses]);

  const totalMyProgramLectures = useMemo(() => {
    if (!currentProgram || programCourseCodeSet.size === 0) return [];
    return sortLectureItems(
      acceptedAllLectures.filter((lecture) => programCourseCodeSet.has(lecture.courseCodeNormalized)),
    );
  }, [acceptedAllLectures, currentProgram, programCourseCodeSet]);

  const filteredMyProgramLectures = useMemo(() => {
    if (!normalizedQuery) return totalMyProgramLectures;
    return totalMyProgramLectures.filter((item) => lectureMatchesQuery(item, normalizedQuery));
  }, [normalizedQuery, totalMyProgramLectures]);

  const filteredAllLectureCount = groupedAllLectures.reduce(
    (count, group) => count + group.lectures.length,
    0,
  );
  const totalMyCourseLectureCount = totalMyProgramLectures.length;
  const filteredMyCourseLectureCount = filteredMyProgramLectures.length;

  function toggleCourseGroup(courseId: string) {
    setExpandedCourseIds((prev) => (
      prev.includes(courseId)
        ? prev.filter((id) => id !== courseId)
        : [...prev, courseId]
    ));
  }

  function renderLectureCard(item: HomepageLectureItem) {
    const { lecture, courseId, lectureLabel } = item;
    const pdfUrl = buildAssetUrl(lecture.pdf_url);

    return (
      <button
        key={lecture.id}
        type="button"
        className="homepage-lecture-card homepage-lecture-card--interactive"
        onClick={() => onOpenLecture(lecture.id)}
      >
        <div className="homepage-lecture-preview">
          {pdfUrl ? (
            <Document
              file={pdfUrl}
              loading={<div className="homepage-preview-fallback">Loading preview...</div>}
              error={<div className="homepage-preview-fallback">Preview unavailable</div>}
            >
              <Page
                pageNumber={1}
                width={262}
                renderTextLayer={false}
                renderAnnotationLayer={false}
              />
            </Document>
          ) : (
            <div className="homepage-preview-fallback">Preview unavailable</div>
          )}
        </div>
        <div className="homepage-lecture-info">
          <p className="homepage-lecture-course-id">{courseId}</p>
          <p className="homepage-lecture-label">{lectureLabel}</p>
        </div>
      </button>
    );
  }

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

  return (
    <section className="homepage homepage--catalog">
      <div className="homepage-search-shell">
        <input
          type="search"
          className="homepage-search-input"
          placeholder="Search lectures"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
      </div>

      {currentProgram ? (
        <section className="homepage-program-inline">
          <div className="homepage-program-inline-summary">
            <span className="homepage-program-inline-label">Program</span>
            <strong className="homepage-program-inline-value">
              {currentProgram.code} - {currentProgram.name}
            </strong>
          </div>
          <div className="homepage-program-inline-actions">
            {profileOptionsLoading && <span className="homepage-profile-meta">Loading options...</span>}
            <button
              type="button"
              className="homepage-profile-save-btn"
              onClick={() => setIsProgramMenuOpen((prev) => !prev)}
              disabled={programSavePending}
            >
              {isProgramMenuOpen ? "Close" : "Change program"}
            </button>
          </div>

          {isProgramMenuOpen && (
            <div className="homepage-program-popup" role="dialog" aria-label="Change program">
              {profileOptionsError && (
                <p className="homepage-profile-error">{profileOptionsError}</p>
              )}

              <div className="homepage-profile-field">
                <label htmlFor="profile-program-popup">Program</label>
                <select
                  id="profile-program-popup"
                  value={draftProgramId ?? ""}
                  onChange={(event) => {
                    const value = event.target.value;
                    setDraftProgramId(value ? Number(value) : null);
                  }}
                  disabled={profileOptionsLoading || programSavePending}
                >
                  <option value="">Show all</option>
                  {programOptions.map((program) => (
                    <option key={program.id} value={program.id}>
                      {program.code} - {program.name}
                    </option>
                  ))}
                </select>
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
            </div>
          )}

          {profileSaveBanner && (
            <p className={`homepage-profile-banner homepage-profile-banner--${profileSaveBanner.kind}`}>
              {profileSaveBanner.text}
            </p>
          )}
        </section>
      ) : (
        <section className="homepage-profile-section">
          {!profileLoading && (
            <div className="homepage-profile-setup-card">
              <h3>Select your program</h3>
              <p>
                Configure your program to unlock your program courses on the homepage.
              </p>
            </div>
          )}

          <div className="homepage-profile-editor">
            <div className="homepage-profile-editor-header">
              <h3>My study profile</h3>
              {profileOptionsLoading && <span className="homepage-profile-meta">Loading options...</span>}
            </div>

            {profileOptionsError && (
              <p className="homepage-profile-error">{profileOptionsError}</p>
            )}

            <div className="homepage-profile-field">
              <label htmlFor="profile-program">Program</label>
              <select
                id="profile-program"
                value={draftProgramId ?? ""}
                onChange={(event) => {
                  const value = event.target.value;
                  setDraftProgramId(value ? Number(value) : null);
                }}
                disabled={profileOptionsLoading || programSavePending}
              >
                <option value="">Show all</option>
                {programOptions.map((program) => (
                  <option key={program.id} value={program.id}>
                    {program.code} - {program.name}
                  </option>
                ))}
              </select>
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

      <section className="homepage-section">
        <div className="homepage-section-heading">
          <h2>My saved lectures</h2>
          <span>{filteredSavedLectures.length}{mySavedActiveLectures.length !== filteredSavedLectures.length ? ` / ${mySavedActiveLectures.length}` : ""}</span>
        </div>

        {loading && (
          <div className="homepage-loading">
            <span className="spinner spinner--dark-sm" />
          </div>
        )}

        {!loading && mySavedActiveLectures.length === 0 && (
          <p className="homepage-empty">
            You have no saved lectures yet.
          </p>
        )}

        {!loading && mySavedActiveLectures.length > 0 && filteredSavedLectures.length === 0 && (
          <p className="homepage-empty">
            No saved lectures match "{searchQuery.trim()}".
          </p>
        )}

        {!loading && filteredSavedLectures.length > 0 && (
          <div className="homepage-carousel" role="list">
            {filteredSavedLectures.map((lecture) => renderLectureCard(lecture))}
          </div>
        )}
      </section>

      {currentProgram && (
        <section className="homepage-section">
          <div className="homepage-section-heading">
            <h2>My courses</h2>
            <span>
              {filteredMyCourseLectureCount}
              {totalMyCourseLectureCount !== filteredMyCourseLectureCount ? ` / ${totalMyCourseLectureCount}` : ""}
            </span>
          </div>

          {loading && (
            <div className="homepage-loading">
              <span className="spinner spinner--dark-sm" />
            </div>
          )}

          {!loading && programCourses.length === 0 && (
            <p className="homepage-empty">
              No active courses are mapped to this program yet.
            </p>
          )}

          {!loading && programCourses.length > 0 && totalMyCourseLectureCount === 0 && (
            <p className="homepage-empty">
              No lectures are available for this program yet.
            </p>
          )}

          {!loading && totalMyCourseLectureCount > 0 && filteredMyCourseLectureCount === 0 && (
            <p className="homepage-empty">
              No lectures match "{searchQuery.trim()}" for this program.
            </p>
          )}

          {!loading && filteredMyCourseLectureCount > 0 && (
            <div className="homepage-carousel" role="list">
              {filteredMyProgramLectures.map((lecture) => renderLectureCard(lecture))}
            </div>
          )}
        </section>
      )}

      <section className="homepage-section">
        <div className="homepage-section-heading">
          <h2>Courses</h2>
          <span>{filteredAllLectureCount}{acceptedAllLectures.length !== filteredAllLectureCount ? ` / ${acceptedAllLectures.length}` : ""}</span>
        </div>

        {loading && (
          <div className="homepage-loading">
            <span className="spinner spinner--dark-sm" />
          </div>
        )}

        {!loading && acceptedAllLectures.length === 0 && (
          <p className="homepage-empty">
            No lectures are available yet.
          </p>
        )}

        {!loading && acceptedAllLectures.length > 0 && filteredAllLectureCount === 0 && (
          <p className="homepage-empty">
            No lectures match "{searchQuery.trim()}".
          </p>
        )}

        {!loading && groupedAllLectures.length > 0 && (
          <div className="homepage-course-groups">
            {groupedAllLectures.map((group, groupIndex) => {
              const isExpanded = expandedCourseIds.includes(group.courseId);
              const panelId = `homepage-course-panel-${groupIndex}`;
              return (
                <div key={group.courseId} className="homepage-course-group">
                  <button
                    type="button"
                    className={`homepage-course-toggle${isExpanded ? " homepage-course-toggle--open" : ""}`}
                    onClick={() => toggleCourseGroup(group.courseId)}
                    aria-expanded={isExpanded}
                    aria-controls={panelId}
                  >
                    <span className="homepage-course-group-title">{group.courseId}</span>
                    <span className="homepage-course-group-meta">
                      <span className="homepage-course-group-count">{group.lectures.length}</span>
                      <span className="homepage-course-group-chevron">▾</span>
                    </span>
                  </button>
                  {isExpanded && (
                    <div className="homepage-carousel" role="list" id={panelId}>
                      {group.lectures.map((lecture) => renderLectureCard(lecture))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </section>
  );
}
