import { useState, type KeyboardEvent } from "react";
import ProcessChat, { type ProcessChatEntry } from "./ProcessChat";
import type { TeachersNoteSummary, UploadProcessJobStatus } from "../types";

interface SidebarProps {
  savedLectures: TeachersNoteSummary[];
  archivedLectures: TeachersNoteSummary[];
  deletedLectures: TeachersNoteSummary[];
  loading: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onNewLecture: () => void;
  onGoHome: () => void;
  onRestore: (id: number) => void;
  showUploadConsole: boolean;
  uploadLoadingLabel: string;
  processJob: UploadProcessJobStatus | null;
  processChat: ProcessChatEntry[];
  processingLectureName?: string | null;
  isAdmin?: boolean;
  currentUserId?: string;
  onOpenAdminPanel?: () => void;
  onRegisterAdmin?: () => void;
  onLogout?: () => void;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
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
  savedLectures,
  archivedLectures,
  deletedLectures,
  loading,
  selectedId,
  onSelect,
  onNewLecture,
  onGoHome,
  onRestore,
  showUploadConsole,
  uploadLoadingLabel,
  processJob,
  processChat,
  processingLectureName,
  isAdmin,
  currentUserId,
  onOpenAdminPanel,
  onRegisterAdmin,
  onLogout,
}: SidebarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const showDeletedSection = Boolean(isAdmin);
  const handleLogoKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onGoHome();
    }
  };

  function renderLectureCard(lecture: TeachersNoteSummary) {
    const isPendingOwn = lecture.is_approved === false && lecture.uploaded_by === currentUserId;
    const lectureDisplayName = formatLectureDisplayName(lecture);
    return (
      <button
        key={lecture.id}
        className={`lecture-card${selectedId === lecture.id ? " active" : ""}${isPendingOwn ? " lecture-card--pending" : ""}`}
        onClick={() => onSelect(lecture.id)}
      >
        <span className="lecture-card-icon">📄</span>
        <span className="lecture-card-body">
          <span className="lecture-card-name">{lectureDisplayName}</span>
          <span className="lecture-card-date">{formatDate(lecture.created_at)}</span>
          {isPendingOwn && (
            <span className="lecture-card-pending-badge">⏳ Pending approval</span>
          )}
        </span>
      </button>
    );
  }

  return (
    <aside className={`sidebar${showUploadConsole ? " sidebar--with-upload-console" : ""}`}>
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
        <button className="sidebar-new-btn" onClick={onNewLecture}>
          + New Lecture
        </button>
      </div>

      {showUploadConsole && (
        <div className="sidebar-upload-console">
          <ProcessChat
            entries={processChat}
            job={processJob}
            variant="sidebar"
            statusLabel={uploadLoadingLabel}
            lectureName={processingLectureName}
          />
        </div>
      )}

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

        {archiveOpen && (
          <div className="sidebar-group sidebar-group--archived">
            <div className="sidebar-section-header">
              <span className="sidebar-section-header-label">Archived</span>
              <button className="sidebar-section-close-btn" onClick={() => setArchiveOpen(false)}>✕</button>
            </div>
            <div className="sidebar-list sidebar-list--archived">
              {!loading && archivedLectures.length === 0 && (
                <p className="sidebar-empty">No archived lectures</p>
              )}
              {!loading && archivedLectures.map((lecture) => renderLectureCard(lecture))}
            </div>
          </div>
        )}

        {showDeletedSection && trashOpen && (
          <div className="sidebar-group sidebar-group--deleted">
            <div className="sidebar-section-header">
              <span className="sidebar-section-header-label">Recently Deleted</span>
              <button className="sidebar-section-close-btn" onClick={() => setTrashOpen(false)}>✕</button>
            </div>
            <div className="sidebar-list sidebar-list--deleted">
              {!loading && deletedLectures.length === 0 && (
                <p className="sidebar-empty">Nothing here</p>
              )}
              {!loading && deletedLectures.map((lecture) => (
                <div key={lecture.id} className="lecture-card lecture-card--deleted">
                  <span className="lecture-card-icon">🗑</span>
                  <span className="lecture-card-body">
                    <span className="lecture-card-name">{formatLectureDisplayName(lecture)}</span>
                    <span className="lecture-card-date">{formatDate(lecture.created_at)}</span>
                  </span>
                  <button
                    className="lecture-card-restore-btn"
                    onClick={() => onRestore(lecture.id)}
                    title="Restore lecture"
                  >
                    Restore
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="sidebar-bottom-menu">
        <button
          className="sidebar-menu-btn"
          onClick={() => setMenuOpen((prev) => !prev)}
        >
          ☰ More
        </button>
        {menuOpen && (
          <div className="sidebar-menu-popup">
            <button
              className="sidebar-menu-item"
              onClick={() => {
                setArchiveOpen((prev) => !prev);
                setMenuOpen(false);
              }}
            >
              <span className="sidebar-menu-item-label">📦 Archived</span>
              <span className="sidebar-menu-item-count">{archivedLectures.length}</span>
            </button>
            {showDeletedSection && (
              <button
                className="sidebar-menu-item"
                onClick={() => {
                  setTrashOpen((prev) => !prev);
                  setMenuOpen(false);
                }}
              >
                <span className="sidebar-menu-item-label">🗑 Recently Deleted</span>
                <span className="sidebar-menu-item-count">{deletedLectures.length}</span>
              </button>
            )}
            {isAdmin && onOpenAdminPanel && (
              <button
                className="sidebar-menu-item"
                onClick={() => {
                  setMenuOpen(false);
                  onOpenAdminPanel();
                }}
              >
                <span className="sidebar-menu-item-label">⚙ Admin Panel</span>
              </button>
            )}
            {isAdmin && onLogout && (
              <button
                className="sidebar-menu-item sidebar-menu-item--danger"
                onClick={() => {
                  setMenuOpen(false);
                  onLogout();
                }}
              >
                <span className="sidebar-menu-item-label">↩ Log out as admin</span>
              </button>
            )}
            {!isAdmin && onRegisterAdmin && (
              <button
                className="sidebar-menu-item"
                onClick={() => {
                  setMenuOpen(false);
                  onRegisterAdmin();
                }}
              >
                <span className="sidebar-menu-item-label">🔓 Register as admin</span>
              </button>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
