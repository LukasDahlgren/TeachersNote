import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { AuthUser, Course, Program, StudentProfile, TeachersNoteSummary } from "../types";
import { getPublicPrograms, updateProfileProgram, getProfile } from "../api";
import ProgramPicker from "./ProgramPicker";

interface Props {
  authUser: AuthUser;
  profile: StudentProfile | null;
  isAdmin: boolean;
  archivedLectures: TeachersNoteSummary[];
  deletedLectures: TeachersNoteSummary[];
  onLogout: () => void;
  onRestore: (id: number) => void;
  onProfileChange: (profile: StudentProfile) => void;
  onSelectLecture: (id: number) => void;
}

function getInitials(name: string | null, email: string): string {
  if (name?.trim()) {
    return name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0])
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
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function ProfilePage({
  authUser,
  profile,
  isAdmin,
  archivedLectures,
  deletedLectures,
  onLogout,
  onRestore,
  onProfileChange,
  onSelectLecture,
}: Props) {
  const navigate = useNavigate();

  // Program editing
  const [programs, setPrograms] = useState<Program[]>([]);
  const [programsLoading, setProgramsLoading] = useState(false);
  const [editingProgram, setEditingProgram] = useState(false);
  const [pendingProgramId, setPendingProgramId] = useState<number | null>(null);
  const [savingProgram, setSavingProgram] = useState(false);
  const [programBanner, setProgramBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  // Archive / trash toggles
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);

  // Restore state
  const [restoringId, setRestoringId] = useState<number | null>(null);

  useEffect(() => {
    setProgramsLoading(true);
    getPublicPrograms()
      .then(setPrograms)
      .catch(() => setPrograms([]))
      .finally(() => setProgramsLoading(false));
  }, []);

  function openEditProgram() {
    setPendingProgramId(profile?.program?.id ?? null);
    setEditingProgram(true);
    setProgramBanner(null);
  }

  async function saveProgram() {
    setSavingProgram(true);
    setProgramBanner(null);
    try {
      await updateProfileProgram(pendingProgramId);
      const next = await getProfile();
      onProfileChange(next);
      setEditingProgram(false);
      setProgramBanner({ kind: "success", text: "Program updated." });
      setTimeout(() => setProgramBanner(null), 3000);
    } catch {
      setProgramBanner({ kind: "error", text: "Failed to save. Please try again." });
    } finally {
      setSavingProgram(false);
    }
  }

  async function handleRestore(id: number) {
    setRestoringId(id);
    try {
      onRestore(id);
    } finally {
      setRestoringId(null);
    }
  }

  const currentProgram = profile?.program ?? null;
  const selectedCourses: Course[] = profile?.selected_courses ?? [];

  return (
    <div className="profile-page">
      <div className="profile-page-inner">

        {/* Back button */}
        <button className="profile-back-btn" onClick={() => navigate("/")}>
          ← Back
        </button>

        {/* User card */}
        <div className="profile-card">
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

        {/* School & Program */}
        <section className="profile-section">
          <h2 className="profile-section-title">School &amp; Program</h2>
          <div className="profile-program-block">
            <div className="profile-program-row">
              <div>
                <div className="profile-program-label">School</div>
                <div className="profile-program-value">
                  {currentProgram ? "Stockholms universitet" : "—"}
                </div>
              </div>
              <div>
                <div className="profile-program-label">Program</div>
                <div className="profile-program-value">
                  {currentProgram
                    ? `${currentProgram.name} (${currentProgram.code})`
                    : "Not set"}
                </div>
              </div>
              {!editingProgram && (
                <button className="profile-program-change-btn" onClick={openEditProgram}>
                  {currentProgram ? "Change" : "Set program"}
                </button>
              )}
            </div>

            {editingProgram && (
              <div className="profile-program-editor">
                <label className="profile-program-editor-label">Select program</label>
                <ProgramPicker
                  value={pendingProgramId}
                  programs={programs}
                  onChange={setPendingProgramId}
                  disabled={programsLoading || savingProgram}
                  placeholder={programsLoading ? "Loading programs…" : "Select a program"}
                />
                <div className="profile-program-editor-actions">
                  <button
                    className="profile-program-save-btn"
                    onClick={saveProgram}
                    disabled={savingProgram}
                  >
                    {savingProgram ? "Saving…" : "Save"}
                  </button>
                  <button
                    className="profile-program-cancel-btn"
                    onClick={() => setEditingProgram(false)}
                    disabled={savingProgram}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {programBanner && (
              <p className={`profile-banner profile-banner--${programBanner.kind}`}>
                {programBanner.text}
              </p>
            )}
          </div>
        </section>

        {/* Enrolled courses */}
        {selectedCourses.length > 0 && (
          <section className="profile-section">
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

        {/* Archived lectures */}
        <section className="profile-section">
          <button
            className="profile-collapsible-header"
            onClick={() => setArchiveOpen((v) => !v)}
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
                archivedLectures.map((lec) => (
                  <button
                    key={lec.id}
                    className="profile-lecture-item"
                    onClick={() => { onSelectLecture(lec.id); navigate("/lectures/" + lec.id); }}
                  >
                    <span className="profile-lecture-icon">📄</span>
                    <span className="profile-lecture-body">
                      <span className="profile-lecture-name">{lec.name}</span>
                      <span className="profile-lecture-date">{formatShortDate(lec.created_at)}</span>
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </section>

        {/* Recently deleted (admin only) */}
        {isAdmin && (
          <section className="profile-section">
            <button
              className="profile-collapsible-header"
              onClick={() => setTrashOpen((v) => !v)}
            >
              <span>🗑 Recently Deleted</span>
              <span className="profile-collapsible-count">{deletedLectures.length}</span>
              <span className="profile-collapsible-chevron">{trashOpen ? "▴" : "▾"}</span>
            </button>
            {trashOpen && (
              <div className="profile-lecture-list">
                {deletedLectures.length === 0 ? (
                  <p className="profile-empty">Nothing here.</p>
                ) : (
                  deletedLectures.map((lec) => (
                    <div key={lec.id} className="profile-lecture-item profile-lecture-item--deleted">
                      <span className="profile-lecture-icon">🗑</span>
                      <span className="profile-lecture-body">
                        <span className="profile-lecture-name">{lec.name}</span>
                        <span className="profile-lecture-date">{formatShortDate(lec.created_at)}</span>
                      </span>
                      <button
                        className="profile-restore-btn"
                        disabled={restoringId === lec.id}
                        onClick={() => handleRestore(lec.id)}
                      >
                        Restore
                      </button>
                    </div>
                  ))
                )}
              </div>
            )}
          </section>
        )}

        {/* Admin + Logout */}
        <section className="profile-section profile-section--actions">
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
            onClick={onLogout}
          >
            ↩ Log out
          </button>
        </section>

      </div>
    </div>
  );
}
