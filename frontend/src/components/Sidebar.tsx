import type { LectureSummary } from "../types";

interface SidebarProps {
  lectures: LectureSummary[];
  loading: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onNewLecture: () => void;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function Sidebar({ lectures, loading, selectedId, onSelect, onNewLecture }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">LectureSummary</div>

      <div className="sidebar-new-btn-wrap">
        <button className="sidebar-new-btn" onClick={onNewLecture}>
          + New Lecture
        </button>
      </div>

      <div className="sidebar-section-label">My Lectures</div>

      <div className="sidebar-list">
        {loading && (
          <div className="sidebar-spinner">
            <span className="spinner spinner--dark-sm" />
          </div>
        )}

        {!loading && lectures.length === 0 && (
          <p className="sidebar-empty">No lectures yet</p>
        )}

        {!loading && lectures.map((lec) => (
          <button
            key={lec.id}
            className={`lecture-card${selectedId === lec.id ? " active" : ""}`}
            onClick={() => onSelect(lec.id)}
          >
            <span className="lecture-card-icon">📄</span>
            <span className="lecture-card-body">
              <span className="lecture-card-name">{lec.name}</span>
              <span className="lecture-card-date">{formatDate(lec.created_at)}</span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
