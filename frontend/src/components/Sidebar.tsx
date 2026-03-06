import { type KeyboardEvent } from "react";
import type { TeachersNoteSummary } from "../types";

interface SidebarProps {
  collapsed?: boolean;
  savedLectures: TeachersNoteSummary[];
  loading: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onNewLecture: () => void;
  newLectureButtonRef?: (el: HTMLButtonElement | null) => void;
  isNewLectureOverlayOpen?: boolean;
  onGoHome: () => void;
  currentUserId?: string;
  onOpenProfile?: () => void;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function normalizeCourseToken(value: string | null | undefined): string {
  return (value ?? "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function formatLectureDisplayName(lecture: TeachersNoteSummary): string {
  const rawName = lecture.name ?? "";
  const name = rawName.trim();
  if (!name) return rawName;

  const courseId = (lecture.course_id ?? "").trim();
  const courseDisplay = (lecture.course_display ?? "").trim();
  if (!courseId || !courseDisplay) return rawName;
  if (normalizeCourseToken(courseId) === normalizeCourseToken(courseDisplay)) return rawName;

  const prefixPattern = new RegExp(`^${escapeRegex(courseId)}(?=($|[-_\\s]))`, "i");
  if (prefixPattern.test(name)) {
    return name.replace(prefixPattern, courseDisplay);
  }

  const firstToken = name.split(/[-_\s]+/, 1)[0] ?? "";
  if (normalizeCourseToken(firstToken) === normalizeCourseToken(courseId)) {
    return `${courseDisplay}${name.slice(firstToken.length)}`;
  }

  return rawName;
}

export default function Sidebar({
  collapsed = false,
  savedLectures,
  loading,
  selectedId,
  onSelect,
  onNewLecture,
  newLectureButtonRef,
  isNewLectureOverlayOpen = false,
  onGoHome,
  currentUserId: _currentUserId,
  onOpenProfile,
}: SidebarProps) {
  const handleLogoKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onGoHome();
    }
  };

  function renderLectureCard(lecture: TeachersNoteSummary) {
    const lectureDisplayName = formatLectureDisplayName(lecture);
    return (
      <button
        key={lecture.id}
        className={`lecture-card${selectedId === lecture.id ? " active" : ""}`}
        onClick={() => onSelect(lecture.id)}
      >
        <span className="lecture-card-icon">📄</span>
        <span className="lecture-card-body">
          <span className="lecture-card-name">{lectureDisplayName}</span>
          <span className="lecture-card-date">{formatDate(lecture.created_at)}</span>
        </span>
      </button>
    );
  }

  return (
    <aside className={`sidebar${collapsed ? " sidebar--collapsed" : ""}`}>
      <div
        className="sidebar-logo"
        role="button"
        tabIndex={0}
        onClick={onGoHome}
        onKeyDown={handleLogoKeyDown}
      >
        TeachersNote
      </div>

      <div className="sidebar-new-btn-wrap">
        <button
          type="button"
          className="sidebar-new-btn"
          onClick={onNewLecture}
          ref={newLectureButtonRef}
          aria-haspopup="dialog"
          aria-expanded={isNewLectureOverlayOpen}
          aria-controls="new-lecture-overlay-panel"
        >
          + New Lecture
        </button>
      </div>

      <div className="sidebar-groups">
        <div className="sidebar-group sidebar-group--active">
          <div className="sidebar-section-label">Saved lectures</div>
          <div className="sidebar-list sidebar-list--active">
            {loading && (
              <div className="sidebar-spinner">
                <span className="spinner spinner--dark-sm" />
              </div>
            )}

            {!loading && savedLectures.length === 0 && (
              <p className="sidebar-empty">No lectures yet</p>
            )}

            {!loading && savedLectures.map((lecture) => renderLectureCard(lecture))}
          </div>
        </div>
      </div>

      <div className="sidebar-bottom-menu">
        <button
          className="sidebar-menu-btn"
          onClick={onOpenProfile}
        >
          👤 Profile
        </button>
      </div>
    </aside>
  );
}
