import type { KeyboardEvent } from "react";
import type { LectureSummary } from "../types";

interface SidebarProps {
  lectures: LectureSummary[];
  loading: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onNewLecture: () => void;
  onGoHome: () => void;
  demoMode: boolean;
  onToggleDemo: () => void;
  onRunDemo: () => void;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function Sidebar({
  lectures,
  loading,
  selectedId,
  onSelect,
  onNewLecture,
  onGoHome,
  demoMode,
  onToggleDemo,
  onRunDemo,
}: SidebarProps) {
  const activeLectures = lectures.filter((lecture) => !lecture.is_archived);
  const archivedLectures = lectures.filter((lecture) => lecture.is_archived);
  const handleLogoKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onGoHome();
    }
  };

  function renderLectureCard(lecture: LectureSummary) {
    return (
      <button
        key={lecture.id}
        className={`lecture-card${selectedId === lecture.id ? " active" : ""}`}
        onClick={() => onSelect(lecture.id)}
      >
        <span className="lecture-card-icon">📄</span>
        <span className="lecture-card-body">
          <span className="lecture-card-name">{lecture.name}</span>
          <span className="lecture-card-date">{formatDate(lecture.created_at)}</span>
        </span>
      </button>
    );
  }

  return (
    <aside className="sidebar">
      <div
        className="sidebar-logo"
        role="button"
        tabIndex={0}
        onClick={onGoHome}
        onKeyDown={handleLogoKeyDown}
      >
        LectureSummary
      </div>

      <div className="sidebar-new-btn-wrap">
        <button className="sidebar-new-btn" onClick={onNewLecture}>
          + New Lecture
        </button>
        <button
          className={`sidebar-demo-toggle${demoMode ? " active" : ""}`}
          onClick={onToggleDemo}
        >
          Demo Mode: {demoMode ? "On" : "Off"}
        </button>
        {demoMode && (
          <button className="sidebar-demo-run" onClick={onRunDemo}>
            Run F2VT26 Demo
          </button>
        )}
      </div>

      <div className="sidebar-groups">
        <div className="sidebar-group sidebar-group--active">
          <div className="sidebar-section-label">My Lectures</div>
          <div className="sidebar-list sidebar-list--active">
            {loading && (
              <div className="sidebar-spinner">
                <span className="spinner spinner--dark-sm" />
              </div>
            )}

            {!loading && activeLectures.length === 0 && (
              <p className="sidebar-empty">No lectures yet</p>
            )}

            {!loading && activeLectures.map((lecture) => renderLectureCard(lecture))}
          </div>
        </div>

        <div className="sidebar-group sidebar-group--archived">
          <div className="sidebar-section-label">Archived</div>
          <div className="sidebar-list sidebar-list--archived">
            {!loading && archivedLectures.length === 0 && (
              <p className="sidebar-empty">No archived lectures</p>
            )}
            {!loading && archivedLectures.map((lecture) => renderLectureCard(lecture))}
          </div>
        </div>
      </div>
    </aside>
  );
}
