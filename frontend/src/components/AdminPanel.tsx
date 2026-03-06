import { useAdminPanelState } from "../hooks/useAdminPanelState";
import ConfirmDialog from "./ConfirmDialog";
import InputDialog from "./InputDialog";
import LectureReviewModal from "./LectureReviewModal";
import RegenerateNotesModal from "./RegenerateNotesModal";

interface AdminPanelProps {
  onBack: () => void;
}

type AdminTab = "lectures" | "courses" | "catalog";

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

export default function AdminPanel({ onBack }: AdminPanelProps) {
  const {
    actionInFlight,
    activeTab,
    approvedLectures,
    catalogDryRun,
    catalogResult,
    catalogSnapshotDate,
    courseSearch,
    courses,
    dialog,
    error,
    filteredCourses,
    filteredLectures,
    handleCourseCode,
    handleCourseDisplayCode,
    handleCourseRename,
    handleCreateCourse,
    handleDeleteLecture,
    handleOpenLecture,
    handleRegenerateNotes,
    handleReject,
    handleRunCatalogSync,
    handleToggleCourse,
    lectureSearch,
    loading,
    newCourseCode,
    newCourseDisplayCode,
    newCourseName,
    openCourseActionsFor,
    openLectureActionsFor,
    regenerateJobStatus,
    reviewLecture,
    setActionInFlight,
    setActiveTab,
    setCatalogDryRun,
    setCatalogSnapshotDate,
    setCourseSearch,
    setDialog,
    setLectureSearch,
    setNewCourseCode,
    setNewCourseDisplayCode,
    setNewCourseName,
    setOpenCourseActionsFor,
    setOpenLectureActionsFor,
    setRegenerateJobStatus,
    setReviewLecture,
    setShowCreateCourse,
    showCreateCourse,
  } = useAdminPanelState();

  return (
    <>
      {dialog?.type === "confirm-reject" && (
        <ConfirmDialog
          message="Reject and permanently delete this lecture?"
          onConfirm={() => {
            const id = dialog.id;
            setDialog(null);
            void handleReject(id);
          }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.type === "confirm-delete" && (
        <ConfirmDialog
          message={`Permanently delete "${dialog.lecture.name}"? This removes the lecture, PPTX, PDF, and stored notes.`}
          onConfirm={() => {
            const lecture = dialog.lecture;
            setDialog(null);
            void handleDeleteLecture(lecture);
          }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.type === "edit-course-name" && (
        <InputDialog
          label="Course name"
          initialValue={dialog.course.name}
          onConfirm={(value) => {
            const course = dialog.course;
            setDialog(null);
            void handleCourseRename(course, value.trim());
          }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.type === "edit-course-code" && (
        <InputDialog
          label="CourseID"
          initialValue={dialog.course.code}
          onConfirm={(value) => {
            const course = dialog.course;
            setDialog(null);
            void handleCourseCode(course, value.trim());
          }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.type === "edit-course-display-code" && (
        <InputDialog
          label="Course display code (leave blank to clear)"
          initialValue={dialog.course.display_code ?? ""}
          onConfirm={(value) => {
            const course = dialog.course;
            setDialog(null);
            void handleCourseDisplayCode(course, value);
          }}
          onCancel={() => setDialog(null)}
        />
      )}
      <div className="admin-panel app-surface app-surface--stagger">
        <div className="admin-panel-header app-surface-item app-surface-item--1">
          <button className="admin-panel-back-btn" onClick={onBack}>← Back</button>
          <h1 className="admin-panel-title">Admin Panel</h1>
        </div>

        <div className="admin-panel-tabs app-surface-item app-surface-item--2" role="tablist" aria-label="Admin sections">
          {[
            { key: "lectures", label: `Lectures (${approvedLectures.length})` },
            { key: "courses", label: `Courses (${courses.length})` },
            { key: "catalog", label: "Catalog sync" },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              className={`admin-panel-tab${activeTab === tab.key ? " admin-panel-tab--active" : ""}`}
              onClick={() => setActiveTab(tab.key as AdminTab)}
              aria-selected={activeTab === tab.key}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {error && <p className="admin-panel-error app-surface-item app-surface-item--3">{error}</p>}
        {loading && <p className="admin-panel-loading app-surface-item app-surface-item--3">Loading…</p>}

        {!loading && activeTab === "lectures" && (
          <section className="admin-panel-section app-surface-item app-surface-item--3">
            <h2 className="admin-panel-section-title">Approved Lectures</h2>
            {approvedLectures.length === 0 && (
              <p className="admin-panel-empty">No approved lectures.</p>
            )}
            {approvedLectures.length > 0 && (
              <>
                <div className="admin-panel-search-row">
                  <input
                    className="admin-panel-input"
                    placeholder="Search lectures…"
                    value={lectureSearch}
                    onChange={(e) => setLectureSearch(e.target.value)}
                  />
                  {lectureSearch.trim() && (
                    <span className="admin-panel-search-count">{filteredLectures.length} of {approvedLectures.length}</span>
                  )}
                </div>
                <table className="admin-panel-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Course</th>
                      <th>Date</th>
                      <th className="admin-panel-actions-header">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredLectures.length === 0 && (
                      <tr><td colSpan={4} className="admin-panel-cell--muted">No lectures match your search.</td></tr>
                    )}
                    {filteredLectures.map((lecture) => {
                      const isActionsOpen = openLectureActionsFor === lecture.id;
                      return (
                        <tr key={lecture.id}>
                          <td>
                            <button
                              type="button"
                              className="admin-panel-lecture-link"
                              onClick={() => handleOpenLecture(lecture.id)}
                            >
                              {lecture.name}
                            </button>
                          </td>
                          <td className="admin-panel-cell--muted">{lecture.course_display || lecture.course_id}</td>
                          <td className="admin-panel-cell--muted">{formatDate(lecture.created_at)}</td>
                          <td className="admin-panel-actions admin-panel-actions--lectures">
                            <button
                              type="button"
                              className="admin-panel-secondary-btn"
                              aria-expanded={isActionsOpen}
                              onClick={() => setOpenLectureActionsFor((current) => (current === lecture.id ? null : lecture.id))}
                            >
                              Actions
                            </button>
                            {isActionsOpen && (
                              <div className="admin-panel-row-actions-menu">
                                <button
                                  type="button"
                                  className="admin-panel-secondary-btn"
                                  onClick={() => {
                                    setOpenLectureActionsFor(null);
                                    handleOpenLecture(lecture.id);
                                  }}
                                >
                                  Open
                                </button>
                                <button
                                  type="button"
                                  className="admin-panel-secondary-btn"
                                  disabled={actionInFlight === `regen-${lecture.id}`}
                                  onClick={() => {
                                    setOpenLectureActionsFor(null);
                                    void handleRegenerateNotes(lecture.id);
                                  }}
                                >
                                  {actionInFlight === `regen-${lecture.id}` ? "Starting..." : "Regenerate notes"}
                                </button>
                                <button
                                  type="button"
                                  className="admin-panel-reject-btn"
                                  disabled={actionInFlight === `lecture-delete-${lecture.id}`}
                                  onClick={() => {
                                    setOpenLectureActionsFor(null);
                                    setDialog({
                                      type: "confirm-delete",
                                      lecture: { id: lecture.id, name: lecture.name },
                                    });
                                  }}
                                >
                                  {actionInFlight === `lecture-delete-${lecture.id}` ? "Deleting..." : "Delete"}
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>
            )}
          </section>
        )}

        {!loading && activeTab === "courses" && (
          <section className="admin-panel-section app-surface-item app-surface-item--3">
            <h2 className="admin-panel-section-title">
              Courses
              <button
                className="admin-panel-add-toggle-btn"
                title={showCreateCourse ? "Cancel" : "Add course"}
                onClick={() => setShowCreateCourse((value) => !value)}
              >
                {showCreateCourse ? "✕" : "+"}
              </button>
            </h2>
            {showCreateCourse && (
              <div className="admin-panel-create-row">
                <input
                  className="admin-panel-input"
                  placeholder="CourseID (e.g. IB132N)"
                  value={newCourseCode}
                  onChange={(event) => setNewCourseCode(event.target.value)}
                />
                <input
                  className="admin-panel-input"
                  placeholder="Display code (optional)"
                  value={newCourseDisplayCode}
                  onChange={(event) => setNewCourseDisplayCode(event.target.value)}
                />
                <input
                  className="admin-panel-input"
                  placeholder="Name"
                  value={newCourseName}
                  onChange={(event) => setNewCourseName(event.target.value)}
                />
                <button
                  className="admin-panel-create-btn"
                  disabled={actionInFlight === "create-course" || !newCourseCode.trim() || !newCourseName.trim()}
                  onClick={() => void handleCreateCourse()}
                >
                  {actionInFlight === "create-course" ? "Creating..." : "Create"}
                </button>
              </div>
            )}
            <div className="admin-panel-search-row">
              <input
                className="admin-panel-input"
                placeholder="Search courses…"
                value={courseSearch}
                onChange={(e) => setCourseSearch(e.target.value)}
              />
              {courseSearch.trim() && (
                <span className="admin-panel-search-count">{filteredCourses.length} of {courses.length}</span>
              )}
            </div>
            <table className="admin-panel-table">
              <thead>
                <tr>
                  <th>CourseID</th>
                  <th>Display</th>
                  <th>Name</th>
                  <th>Status</th>
                  <th className="admin-panel-actions-header">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredCourses.length === 0 && (
                  <tr><td colSpan={5} className="admin-panel-cell--muted">No courses match your search.</td></tr>
                )}
                {filteredCourses.map((course) => {
                  const isActionsOpen = openCourseActionsFor === course.id;
                  return (
                    <tr key={course.id}>
                      <td>{course.code}</td>
                      <td>{course.display_code || "—"}</td>
                      <td>{course.name}</td>
                      <td className="admin-panel-cell--muted">{course.is_active ? "Active" : "Inactive"}</td>
                      <td className="admin-panel-actions admin-panel-actions--courses">
                        <button
                          className="admin-panel-secondary-btn"
                          aria-expanded={isActionsOpen}
                          onClick={() => setOpenCourseActionsFor((current) => (current === course.id ? null : course.id))}
                        >
                          Actions
                        </button>
                        {isActionsOpen && (
                          <div className="admin-panel-row-actions-menu">
                            <button
                              className="admin-panel-secondary-btn"
                              onClick={() => {
                                setOpenCourseActionsFor(null);
                                setDialog({ type: "edit-course-code", course });
                              }}
                            >
                              Edit CourseID
                            </button>
                            <button
                              className="admin-panel-secondary-btn"
                              onClick={() => {
                                setOpenCourseActionsFor(null);
                                setDialog({ type: "edit-course-display-code", course });
                              }}
                            >
                              Edit display
                            </button>
                            <button
                              className="admin-panel-secondary-btn"
                              onClick={() => {
                                setOpenCourseActionsFor(null);
                                setDialog({ type: "edit-course-name", course });
                              }}
                            >
                              Rename
                            </button>
                            <button
                              className="admin-panel-secondary-btn"
                              onClick={() => {
                                setOpenCourseActionsFor(null);
                                void handleToggleCourse(course);
                              }}
                            >
                              {course.is_active ? "Deactivate" : "Activate"}
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        )}

        {!loading && activeTab === "catalog" && (
          <section className="admin-panel-section app-surface-item app-surface-item--3">
            <h2 className="admin-panel-section-title">Catalog sync</h2>
            <p className="admin-panel-cell--muted admin-panel-sync-copy">
              Syncs current Stockholm University DSV catalog into the internal course catalog used by TeachersNote.
            </p>
            <div className="admin-panel-sync-controls">
              <label>
                Snapshot date
                <input
                  className="admin-panel-input"
                  type="date"
                  value={catalogSnapshotDate}
                  onChange={(event) => setCatalogSnapshotDate(event.target.value)}
                />
              </label>
              <label className="admin-panel-sync-checkbox">
                <input
                  type="checkbox"
                  checked={catalogDryRun}
                  onChange={(event) => setCatalogDryRun(event.target.checked)}
                />
                Dry run (no DB writes)
              </label>
              <button
                className="admin-panel-create-btn"
                disabled={actionInFlight === "catalog-sync"}
                onClick={() => void handleRunCatalogSync()}
              >
                {actionInFlight === "catalog-sync" ? "Running..." : "Run sync"}
              </button>
            </div>

            {catalogResult && (
              <div className="admin-panel-sync-result">
                <h3>Latest sync result</h3>
                <div className="admin-panel-sync-metrics">
                  <p>Snapshot: <strong>{catalogResult.snapshot_date}</strong></p>
                  <p>Standalone rows: <strong>{catalogResult.standalone_count}</strong></p>
                  <p>Courses +/{catalogResult.courses_created} ~/{catalogResult.courses_updated} -/{catalogResult.courses_deactivated}</p>
                  <p>Duration: <strong>{catalogResult.duration_seconds}s</strong></p>
                  <p>Mode: <strong>{catalogResult.dry_run ? "Dry run" : "Apply"}</strong></p>
                </div>
                {catalogResult.warnings.length > 0 && (
                  <div className="admin-panel-sync-warnings">
                    <h4>Warnings</h4>
                    <ul>
                      {catalogResult.warnings.map((warning, index) => (
                        <li key={`${index}-${warning}`}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>
        )}
      </div>
      {reviewLecture && (
        <LectureReviewModal
          lecture={reviewLecture}
          onApproved={() => {
            setReviewLecture(null);
          }}
          onRejected={() => {
            setReviewLecture(null);
          }}
          onClose={() => setReviewLecture(null)}
        />
      )}
      {regenerateJobStatus && (
        <RegenerateNotesModal
          lectureTitle={approvedLectures.find((lecture) => lecture.id === regenerateJobStatus.lecture_id)?.name ?? "Unknown"}
          jobStatus={regenerateJobStatus}
          onClose={() => {
            setRegenerateJobStatus(null);
            setActionInFlight(null);
          }}
        />
      )}
    </>
  );
}
