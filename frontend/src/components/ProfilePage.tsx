import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { AuthUser, StudentProfile, TeachersNoteSummary } from "../types";

interface Props {
  authUser: AuthUser;
  profile: StudentProfile | null;
  isAdmin: boolean;
  archivedLectures: TeachersNoteSummary[];
  onLogout: () => void;
  onSelectLecture: (id: number) => void;
}

function getInitials(name: string | null, email: string): string {
  if (name?.trim()) {
    return name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((word) => word[0])
      .join("")
      .toUpperCase();
  }
  return email[0].toUpperCase();
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatShortDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function ProfilePage({
  authUser,
  profile,
  isAdmin,
  archivedLectures,
  onLogout,
  onSelectLecture,
}: Props) {
  const navigate = useNavigate();
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [logoutDialogOpen, setLogoutDialogOpen] = useState(false);

  useEffect(() => {
    if (!logoutDialogOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setLogoutDialogOpen(false);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [logoutDialogOpen]);

  function openLogoutDialog() {
    setLogoutDialogOpen(true);
  }

  function cancelLogoutDialog() {
    setLogoutDialogOpen(false);
  }

  function confirmLogoutDialog() {
    setLogoutDialogOpen(false);
    onLogout();
  }

  const selectedCourses = profile?.selected_courses ?? [];

  return (
    <div className="profile-page app-surface app-surface--stagger">
      <div className="profile-page-inner">
        <button className="profile-back-btn app-surface-item app-surface-item--1" onClick={() => navigate("/")}>
          ← Back
        </button>

        <div className="profile-card app-surface-item app-surface-item--2">
          <div className="profile-avatar">
            {getInitials(authUser.display_name, authUser.email)}
          </div>
          <div className="profile-card-info">
            <div className="profile-display-name">
              {authUser.display_name || authUser.email.split("@")[0]}
            </div>
            <div className="profile-email">{authUser.email}</div>
            <div className="profile-joined">Member since {formatDate(authUser.created_at)}</div>
          </div>
        </div>

        {selectedCourses.length > 0 && (
          <section className="profile-section app-surface-item app-surface-item--3">
            <h2 className="profile-section-title">Enrolled Courses</h2>
            <ul className="profile-course-list">
              {selectedCourses.map((course) => (
                <li key={course.id} className="profile-course-item">
                  <span className="profile-course-code">{course.display_code ?? course.code}</span>
                  <span className="profile-course-name">{course.name}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {isAdmin && (
          <section className="profile-section app-surface-item app-surface-item--5">
            <button
              className="profile-collapsible-header"
              onClick={() => setArchiveOpen((value) => !value)}
            >
              <span>📦 Archived lectures</span>
              <span className="profile-collapsible-count">{archivedLectures.length}</span>
              <span className="profile-collapsible-chevron">{archiveOpen ? "▴" : "▾"}</span>
            </button>
            {archiveOpen && (
              <div className="profile-lecture-list">
                {archivedLectures.length === 0 ? (
                  <p className="profile-empty">No archived lectures.</p>
                ) : (
                  archivedLectures.map((lecture) => (
                    <button
                      key={lecture.id}
                      className="profile-lecture-item"
                      onClick={() => {
                        onSelectLecture(lecture.id);
                        navigate(`/lectures/${lecture.id}`);
                      }}
                    >
                      <span className="profile-lecture-icon">📄</span>
                      <span className="profile-lecture-body">
                        <span className="profile-lecture-name">{lecture.name}</span>
                        <span className="profile-lecture-date">{formatShortDate(lecture.created_at)}</span>
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
          </section>
        )}

        <section className="profile-section profile-section--actions app-surface-item app-surface-item--7">
          {isAdmin && (
            <button
              className="profile-action-btn profile-action-btn--admin"
              onClick={() => navigate("/admin")}
            >
              ⚙ Admin Panel
            </button>
          )}
          <button
            className="profile-action-btn profile-action-btn--logout"
            onClick={openLogoutDialog}
          >
            ↩ Log out
          </button>
        </section>
      </div>
      {logoutDialogOpen && (
        <div
          className="confirm-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="logout-confirm-title"
          onClick={cancelLogoutDialog}
        >
          <div className="confirm-dialog" onClick={(event) => event.stopPropagation()}>
            <h2 id="logout-confirm-title" className="confirm-title">Log out?</h2>
            <p className="confirm-text">You'll need to log in again to access your notes.</p>
            <div className="confirm-actions">
              <button
                type="button"
                className="confirm-cancel-btn"
                onClick={cancelLogoutDialog}
              >
                Cancel
              </button>
              <button
                type="button"
                className="confirm-delete-btn"
                onClick={confirmLogoutDialog}
              >
                Log out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
