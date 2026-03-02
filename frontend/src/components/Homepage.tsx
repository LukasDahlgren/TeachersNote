import { useEffect, useMemo, useState } from "react";
import { Document, Page } from "react-pdf";
import {
  buildAssetUrl,
  getProfileCourseOptions,
  updateProfileCourses,
  updateProfileProgram,
} from "../api";
import type {
  Course,
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
  lectureLabel: string;
  createdAtMs: number;
}

interface CourseLectureGroup {
  courseId: string;
  courseName?: string;
  lectures: HomepageLectureItem[];
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

function lectureMatchesQuery(item: HomepageLectureItem, normalizedQuery: string): boolean {
  if (!normalizedQuery) return true;
  return `${item.lecture.name} ${item.courseId} ${item.lectureLabel}`
    .toLowerCase()
    .includes(normalizedQuery);
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
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [expandedCourseIds, setExpandedCourseIds] = useState<string[]>([]);
  const [expandedMyCourseIds, setExpandedMyCourseIds] = useState<string[]>([]);

  const [profileOptions, setProfileOptions] = useState<ProfileCourseOptions | null>(null);
  const [profileOptionsLoading, setProfileOptionsLoading] = useState(true);
  const [profileOptionsError, setProfileOptionsError] = useState<string | null>(null);
  const [programSavePending, setProgramSavePending] = useState(false);
  const [courseSavePending, setCourseSavePending] = useState(false);
  const [profileSaveBanner, setProfileSaveBanner] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);

  const [draftProgramId, setDraftProgramId] = useState<number | null>(null);
  const [draftCourseIds, setDraftCourseIds] = useState<number[]>([]);

  useEffect(() => {
    setDraftProgramId(profile?.program?.id ?? null);
    setDraftCourseIds(profile?.selected_courses?.map((course) => course.id) ?? []);
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

  const selectedCourses = useMemo(
    () => profile?.selected_courses ?? [],
    [profile],
  );
  const selectedCourseLookup = useMemo(
    () => new Set<number>(draftCourseIds),
    [draftCourseIds],
  );
  const recommendedCourseIds = useMemo(
    () => new Set((profileOptions?.program_courses ?? []).map((course) => course.id)),
    [profileOptions?.program_courses],
  );
  const isProfileConfigured = Boolean(profile?.program) && selectedCourses.length > 0;

  const toLectureItem = (lecture: TeachersNoteSummary): HomepageLectureItem => {
    const parsed = splitLectureName(lecture.name);
    const derivedCourseId = lecture.course_id?.trim() || parsed.courseId;
    return {
      lecture,
      courseId: derivedCourseId,
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
      .filter((lecture) => lecture.is_approved === true && !lecture.is_archived)
      .map(toLectureItem),
    [allLectures],
  );

  const uniqueCourseIds = useMemo(() => {
    const ids = new Set<string>();
    for (const lecture of [...mySavedActiveLectures, ...acceptedAllLectures]) {
      ids.add(lecture.courseId);
    }
    for (const course of selectedCourses) {
      ids.add(course.code);
    }
    return [...ids].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  }, [acceptedAllLectures, mySavedActiveLectures, selectedCourses]);

  const normalizedQuery = normalizeQuery(searchQuery);

  const applySharedFilters = (
    lectures: HomepageLectureItem[],
    searchTextFactory: (item: HomepageLectureItem) => string,
  ): HomepageLectureItem[] => {
    let result = lectures;
    if (selectedCourseId) {
      result = result.filter((lecture) => lecture.courseId === selectedCourseId);
    }
    if (!normalizedQuery) return result;
    return result.filter((lecture) => searchTextFactory(lecture).includes(normalizedQuery));
  };

  const filteredSavedLectures = applySharedFilters(
    mySavedActiveLectures,
    (item) => `${item.lecture.name} ${item.courseId} ${item.lectureLabel}`.toLowerCase(),
  );
  const filteredAllLectures = applySharedFilters(
    acceptedAllLectures,
    (item) => `${item.lecture.name} ${item.courseId} ${item.lectureLabel}`.toLowerCase(),
  );

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
        lectures: lectures.sort((a, b) => {
          if (b.createdAtMs !== a.createdAtMs) return b.createdAtMs - a.createdAtMs;
          return a.lecture.name.localeCompare(b.lecture.name, undefined, { sensitivity: "base" });
        }),
      }));
  })();

  const totalMyCourseLectureCount = useMemo(() => {
    return selectedCourses.reduce((count, course) => {
      const code = course.code.toUpperCase();
      return count + acceptedAllLectures.filter((lecture) => lecture.courseId.toUpperCase() === code).length;
    }, 0);
  }, [acceptedAllLectures, selectedCourses]);

  const groupedMyCourses = useMemo((): CourseLectureGroup[] => {
    const groups: CourseLectureGroup[] = [...selectedCourses]
      .sort((a, b) => a.code.localeCompare(b.code, undefined, { sensitivity: "base" }))
      .map((course) => {
        const courseCode = course.code.toUpperCase();
        const baseLectures = acceptedAllLectures
          .filter((lecture) => lecture.courseId.toUpperCase() === courseCode)
          .sort((a, b) => {
            if (b.createdAtMs !== a.createdAtMs) return b.createdAtMs - a.createdAtMs;
            return a.lecture.name.localeCompare(b.lecture.name, undefined, { sensitivity: "base" });
          });

        let filtered = baseLectures;
        if (selectedCourseId && selectedCourseId !== course.code) {
          filtered = [];
        }
        if (normalizedQuery) {
          const courseMatches = `${course.code} ${course.name}`.toLowerCase().includes(normalizedQuery);
          filtered = courseMatches
            ? filtered
            : filtered.filter((lecture) => lectureMatchesQuery(lecture, normalizedQuery));
        }

        return {
          courseId: course.code,
          courseName: course.name,
          lectures: filtered,
        };
      });

    return groups.filter((group) => group.lectures.length > 0);
  }, [acceptedAllLectures, normalizedQuery, selectedCourseId, selectedCourses]);

  const filteredAllLectureCount = groupedAllLectures.reduce(
    (count, group) => count + group.lectures.length,
    0,
  );
  const filteredMyCourseLectureCount = groupedMyCourses.reduce(
    (count, group) => count + group.lectures.length,
    0,
  );

  function toggleCourseGroup(courseId: string) {
    setExpandedCourseIds((prev) => (
      prev.includes(courseId)
        ? prev.filter((id) => id !== courseId)
        : [...prev, courseId]
    ));
  }

  function toggleMyCourseGroup(courseId: string) {
    setExpandedMyCourseIds((prev) => (
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

  function toggleCourseSelection(courseId: number) {
    setDraftCourseIds((prev) => (
      prev.includes(courseId)
        ? prev.filter((id) => id !== courseId)
        : [...prev, courseId]
    ));
  }

  async function handleSaveProgram() {
    setProgramSavePending(true);
    setProfileSaveBanner(null);
    try {
      const updatedProfile = await updateProfileProgram(draftProgramId);
      onProfileChange(updatedProfile);
      await loadProfileOptions();
      setProfileSaveBanner({ kind: "success", text: "Program saved." });
    } catch (err) {
      setProfileSaveBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to save program.",
      });
    } finally {
      setProgramSavePending(false);
    }
  }

  async function handleSaveCourses() {
    setCourseSavePending(true);
    setProfileSaveBanner(null);
    try {
      const updatedProfile = await updateProfileCourses(draftCourseIds);
      onProfileChange(updatedProfile);
      setProfileSaveBanner({ kind: "success", text: "Courses saved." });
    } catch (err) {
      setProfileSaveBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to save courses.",
      });
    } finally {
      setCourseSavePending(false);
    }
  }

  const programOptions = profileOptions?.programs ?? [];
  const courseOptions = profileOptions?.all_courses ?? [];

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

      {uniqueCourseIds.length >= 1 && (
        <div className="homepage-filter-chips" role="group" aria-label="Filter by course">
          {uniqueCourseIds.map((id) => (
            <button
              key={id}
              type="button"
              className={`homepage-filter-chip${selectedCourseId === id ? " homepage-filter-chip--active" : ""}`}
              onClick={() => setSelectedCourseId(selectedCourseId === id ? null : id)}
              aria-pressed={selectedCourseId === id}
            >
              {id}
            </button>
          ))}
        </div>
      )}

      <section className="homepage-profile-section">
        {!profileLoading && !isProfileConfigured && (
          <div className="homepage-profile-setup-card">
            <h3>Select your program and courses</h3>
            <p>
              Configure your profile to unlock course-specific lecture slides on the homepage.
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
              <option value="">No program selected</option>
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

          <div className="homepage-profile-field">
            <label>Courses</label>
            <div className="homepage-course-multiselect" role="group" aria-label="Select courses">
              {courseOptions.length === 0 && (
                <p className="homepage-profile-empty">No active courses are available.</p>
              )}
              {courseOptions.map((course: Course) => (
                <label key={course.id} className="homepage-course-multiselect-item">
                  <input
                    type="checkbox"
                    checked={selectedCourseLookup.has(course.id)}
                    onChange={() => toggleCourseSelection(course.id)}
                    disabled={courseSavePending || profileOptionsLoading}
                  />
                  <span>{course.code} - {course.name}</span>
                  {recommendedCourseIds.has(course.id) && (
                    <span className="homepage-course-recommended">Recommended</span>
                  )}
                </label>
              ))}
            </div>
            <button
              type="button"
              className="homepage-profile-save-btn"
              onClick={() => void handleSaveCourses()}
              disabled={courseSavePending || profileOptionsLoading}
            >
              {courseSavePending ? "Saving..." : "Save courses"}
            </button>
          </div>

          {profileSaveBanner && (
            <p className={`homepage-profile-banner homepage-profile-banner--${profileSaveBanner.kind}`}>
              {profileSaveBanner.text}
            </p>
          )}
        </div>
      </section>

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

        {!loading && selectedCourses.length === 0 && (
          <p className="homepage-empty">
            Select courses in your profile to unlock course slides.
          </p>
        )}

        {!loading && selectedCourses.length > 0 && groupedMyCourses.length === 0 && (
          <p className="homepage-empty">
            No lectures match your selected courses{normalizedQuery ? ` for "${searchQuery.trim()}"` : ""}.
          </p>
        )}

        {!loading && groupedMyCourses.length > 0 && (
          <div className="homepage-course-groups">
            {groupedMyCourses.map((group, groupIndex) => {
              const isExpanded = expandedMyCourseIds.includes(group.courseId);
              const panelId = `homepage-my-course-panel-${groupIndex}`;
              return (
                <div key={group.courseId} className="homepage-course-group">
                  <button
                    type="button"
                    className={`homepage-course-toggle${isExpanded ? " homepage-course-toggle--open" : ""}`}
                    onClick={() => toggleMyCourseGroup(group.courseId)}
                    aria-expanded={isExpanded}
                    aria-controls={panelId}
                  >
                    <span className="homepage-course-group-title">
                      {group.courseId}
                      {group.courseName ? <small>{group.courseName}</small> : null}
                    </span>
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
            No accepted lectures are available yet.
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
