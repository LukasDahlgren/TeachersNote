import { useMemo, useState } from "react";
import { Document, Page } from "react-pdf";
import { buildAssetUrl } from "../api";
import type { LectureSummary } from "../types";
import { ensurePdfWorker } from "../pdfWorker";

interface HomepageProps {
  lectures: LectureSummary[];
  loading: boolean;
  onOpenLecture: (id: number) => void;
}

interface LectureNameParts {
  courseId: string;
  lectureLabel: string;
}

function stripExtension(value: string): string {
  return value.replace(/\.[^./\\]+$/, "");
}

function splitLectureName(name: string): LectureNameParts {
  const cleanedName = stripExtension(name).replace(/\s+/g, " ").trim();
  if (!cleanedName) {
    return { courseId: "Lecture", lectureLabel: "Lecture" };
  }

  const firstToken = cleanedName.split(/[\s_]+/).filter(Boolean)[0] ?? cleanedName;
  const courseIdPattern = /^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9-]+$/;
  const hyphenCodePattern = /^[A-Za-z]{2,}(?:-[A-Za-z0-9]+)+$/;
  const looksLikeCourseId = courseIdPattern.test(firstToken) || hyphenCodePattern.test(firstToken);

  const courseId = looksLikeCourseId ? firstToken : cleanedName;
  let lectureLabel = cleanedName;
  if (looksLikeCourseId) {
    lectureLabel = cleanedName.slice(firstToken.length).replace(/^[\s_-]+/, "").trim();
  }
  if (!lectureLabel) {
    lectureLabel = cleanedName;
  }

  return { courseId, lectureLabel };
}

ensurePdfWorker();

export default function Homepage({
  lectures,
  loading,
  onOpenLecture,
}: HomepageProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);

  const activeLectures = useMemo(
    () => lectures.filter((lecture) => !lecture.is_archived),
    [lectures],
  );

  const uniqueCourseIds = useMemo(() => {
    const ids = new Set<string>();
    for (const lecture of activeLectures) {
      const { courseId } = splitLectureName(lecture.name);
      if (courseId !== stripExtension(lecture.name).replace(/\s+/g, " ").trim()) {
        ids.add(courseId);
      }
    }
    return [...ids].sort();
  }, [activeLectures]);

  const normalizedQuery = searchQuery.trim().toLowerCase();

  const filteredLectures = useMemo(() => {
    let result = activeLectures;
    if (selectedCourseId) {
      result = result.filter(
        (lecture) => splitLectureName(lecture.name).courseId === selectedCourseId,
      );
    }
    if (!normalizedQuery) return result;
    return result.filter((lecture) =>
      lecture.name.toLowerCase().includes(normalizedQuery),
    );
  }, [activeLectures, selectedCourseId, normalizedQuery]);

  const showNoSearchResults = !loading && activeLectures.length > 0 && filteredLectures.length === 0;
  const placeholderCards = [1, 2, 3, 4];

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

      <section className="homepage-section">
        <div className="homepage-section-heading">
          <h2>My Lectures</h2>
          <span>{filteredLectures.length}{activeLectures.length !== filteredLectures.length ? ` / ${activeLectures.length}` : ""}</span>
        </div>

        {loading && (
          <div className="homepage-loading">
            <span className="spinner spinner--dark-sm" />
          </div>
        )}

        {!loading && activeLectures.length === 0 && (
          <p className="homepage-empty">
            You have no active lectures yet. Start by uploading one in the workspace.
          </p>
        )}

        {showNoSearchResults && (
          <p className="homepage-empty">
            No lectures match "{searchQuery.trim()}".
          </p>
        )}

        {!loading && filteredLectures.length > 0 && (
          <div className="homepage-carousel" role="list">
            {filteredLectures.map((lecture) => {
              const { courseId, lectureLabel } = splitLectureName(lecture.name);
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
            })}
          </div>
        )}
      </section>

      <section className="homepage-section">
        <div className="homepage-section-heading">
          <h2>All Lectures</h2>
          <span>Coming soon</span>
        </div>
        <div className="homepage-carousel" role="list">
          {placeholderCards.map((card) => (
            <article key={card} className="homepage-lecture-card homepage-lecture-card--placeholder">
              <div className="homepage-lecture-preview homepage-lecture-preview--placeholder">
                <span>Coming soon</span>
              </div>
              <div className="homepage-lecture-info">
                <p className="homepage-lecture-course-id">All Lectures</p>
                <p className="homepage-lecture-label">Community lecture catalog coming soon.</p>
              </div>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
