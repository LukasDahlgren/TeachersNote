import { useEffect, useMemo, useState } from "react";
import {
  approveLecture,
  createCourse,
  createProgram,
  getCourses,
  getLectures,
  getPendingLectures,
  getProgramCourses,
  getProgramPlan,
  getPrograms,
  mapProgramCourse,
  rejectLecture,
  runCatalogSync,
  startRegenerateNotesJob,
  unmapProgramCourse,
  updateCourse,
  updateProgram,
} from "../api";
import LectureReviewModal from "./LectureReviewModal";
import ProgramPicker from "./ProgramPicker";
import RegenerateNotesModal from "./RegenerateNotesModal";
import type {
  CatalogSyncResult,
  Course,
  Program,
  ProgramPlanRow,
  RegenerateNotesJobStatus,
  TeachersNoteSummary,
} from "../types";

interface AdminPanelProps {
  onBack: () => void;
}

type AdminTab = "pending" | "programs" | "courses" | "mappings" | "catalog" | "lectures";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function normalizeTermLabel(value: string): string {
  const trimmed = value.trim();
  return trimmed || "Unspecified term";
}

function normalizeGroupLabel(row: ProgramPlanRow): string {
  const raw = row.group_label?.trim() || "";
  if (raw) return raw;
  return row.group_type === "optional" ? "Optional" : "Mandatory";
}

function formatGroupType(groupType: ProgramPlanRow["group_type"]): string {
  return groupType === "optional" ? "Optional" : "Mandatory";
}

export default function AdminPanel({ onBack }: AdminPanelProps) {
  const [activeTab, setActiveTab] = useState<AdminTab>("pending");
  const [pending, setPending] = useState<TeachersNoteSummary[]>([]);
  const [programs, setPrograms] = useState<Program[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [approvedLectures, setApprovedLectures] = useState<TeachersNoteSummary[]>([]);

  const [reviewLecture, setReviewLecture] = useState<TeachersNoteSummary | null>(null);
  const [regenerateJobStatus, setRegenerateJobStatus] = useState<RegenerateNotesJobStatus | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState<string | null>(null);

  const [newProgramCode, setNewProgramCode] = useState("");
  const [newProgramName, setNewProgramName] = useState("");
  const [newCourseCode, setNewCourseCode] = useState("");
  const [newCourseDisplayCode, setNewCourseDisplayCode] = useState("");
  const [newCourseName, setNewCourseName] = useState("");

  const [selectedProgramId, setSelectedProgramId] = useState<number | null>(null);
  const [mappedCourseIds, setMappedCourseIds] = useState<Set<number>>(new Set());
  const [loadingMappings, setLoadingMappings] = useState(false);

  const [catalogSnapshotDate, setCatalogSnapshotDate] = useState("");
  const [catalogDryRun, setCatalogDryRun] = useState(false);
  const [catalogResult, setCatalogResult] = useState<CatalogSyncResult | null>(null);

  const [programPlanRows, setProgramPlanRows] = useState<ProgramPlanRow[]>([]);
  const [loadingProgramPlan, setLoadingProgramPlan] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [pendingData, programData, courseData, lecturesData] = await Promise.all([
        getPendingLectures(),
        getPrograms(),
        getCourses(),
        getLectures(),
      ]);
      setPending(pendingData);
      setPrograms(programData);
      setCourses(courseData);
      setApprovedLectures(lecturesData.filter(l => !l.is_deleted && !l.is_archived));
      if (!selectedProgramId && programData.length > 0) {
        setSelectedProgramId(programData[0].id);
      } else if (
        selectedProgramId
        && !programData.some((program) => program.id === selectedProgramId)
      ) {
        setSelectedProgramId(programData[0]?.id ?? null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin data.");
    } finally {
      setLoading(false);
    }
  }

  async function loadMappings(programId: number) {
    setLoadingMappings(true);
    setError(null);
    try {
      const data = await getProgramCourses(programId);
      setMappedCourseIds(new Set(data.courses.map((course) => course.id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load program-course mappings.");
      setMappedCourseIds(new Set());
    } finally {
      setLoadingMappings(false);
    }
  }

  async function loadProgramPlan(programId: number) {
    setLoadingProgramPlan(true);
    setError(null);
    try {
      const data = await getProgramPlan(programId);
      setProgramPlanRows(data.rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load program plan.");
      setProgramPlanRows([]);
    } finally {
      setLoadingProgramPlan(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedProgramId) {
      setMappedCourseIds(new Set());
      setProgramPlanRows([]);
      return;
    }

    void Promise.all([
      loadMappings(selectedProgramId),
      loadProgramPlan(selectedProgramId),
    ]);
  }, [selectedProgramId]);

  async function handleApprove(id: number) {
    const key = `pending-approve-${id}`;
    setActionInFlight(key);
    try {
      await approveLecture(id);
      setPending((prev) => prev.filter((lecture) => lecture.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve lecture.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleReject(id: number) {
    if (!window.confirm("Reject and delete this lecture?")) return;
    const key = `pending-reject-${id}`;
    setActionInFlight(key);
    try {
      await rejectLecture(id);
      setPending((prev) => prev.filter((lecture) => lecture.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject lecture.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleCreateProgram() {
    const code = newProgramCode.trim();
    const name = newProgramName.trim();
    if (!code || !name) return;
    setActionInFlight("create-program");
    setError(null);
    try {
      await createProgram({ code, name, is_active: true });
      setNewProgramCode("");
      setNewProgramName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create program.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleCreateCourse() {
    const code = newCourseCode.trim();
    const displayCode = newCourseDisplayCode.trim();
    const name = newCourseName.trim();
    if (!code || !name) return;
    setActionInFlight("create-course");
    setError(null);
    try {
      await createCourse({
        code,
        display_code: displayCode || null,
        name,
        is_active: true,
      });
      setNewCourseCode("");
      setNewCourseDisplayCode("");
      setNewCourseName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create course.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleProgramRename(program: Program) {
    const nextName = window.prompt("Program name", program.name)?.trim();
    if (!nextName || nextName === program.name) return;
    const key = `program-rename-${program.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      await updateProgram(program.id, { name: nextName });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update program.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleProgramCode(program: Program) {
    const nextCode = window.prompt("Program code", program.code)?.trim();
    if (!nextCode || nextCode === program.code) return;
    const key = `program-code-${program.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      await updateProgram(program.id, { code: nextCode });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update program code.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleToggleProgram(program: Program) {
    const key = `program-active-${program.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      await updateProgram(program.id, { is_active: !program.is_active });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update program status.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleCourseRename(course: Course) {
    const nextName = window.prompt("Course name", course.name)?.trim();
    if (!nextName || nextName === course.name) return;
    const key = `course-rename-${course.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      await updateCourse(course.id, { name: nextName });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update course.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleCourseCode(course: Course) {
    const nextCode = window.prompt("CourseID", course.code)?.trim();
    if (!nextCode || nextCode === course.code) return;
    const key = `course-code-${course.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      await updateCourse(course.id, { code: nextCode });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update CourseID.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleCourseDisplayCode(course: Course) {
    const nextDisplayCode = window.prompt(
      "Course display code (leave blank to clear)",
      course.display_code ?? "",
    );
    if (nextDisplayCode === null) return;

    const normalized = nextDisplayCode.trim();
    if (normalized === (course.display_code ?? "")) return;

    const key = `course-display-code-${course.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      await updateCourse(course.id, { display_code: normalized || null });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update course display code.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleToggleCourse(course: Course) {
    const key = `course-active-${course.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      await updateCourse(course.id, { is_active: !course.is_active });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update course status.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleMappingToggle(course: Course) {
    if (!selectedProgramId) return;
    const isMapped = mappedCourseIds.has(course.id);
    const key = `mapping-${selectedProgramId}-${course.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      if (isMapped) {
        await unmapProgramCourse(selectedProgramId, course.id);
      } else {
        await mapProgramCourse(selectedProgramId, course.id);
      }
      await loadMappings(selectedProgramId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update mapping.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleRunCatalogSync() {
    const key = "catalog-sync";
    setActionInFlight(key);
    setError(null);
    try {
      const payload: { snapshot_date?: string; dry_run: boolean } = {
        dry_run: catalogDryRun,
      };
      if (catalogSnapshotDate.trim()) {
        payload.snapshot_date = catalogSnapshotDate.trim();
      }
      const result = await runCatalogSync(payload);
      setCatalogResult(result);
      await load();
      if (selectedProgramId) {
        await Promise.all([
          loadMappings(selectedProgramId),
          loadProgramPlan(selectedProgramId),
        ]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run catalog sync.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleRegenerateNotes(lectureId: number) {
    const key = `regen-${lectureId}`;
    setActionInFlight(key);
    setError(null);
    try {
      const job = await startRegenerateNotesJob(lectureId);
      setRegenerateJobStatus(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start regeneration job.");
      setActionInFlight(null);
    }
  }

  const selectedProgram = useMemo(
    () => programs.find((program) => program.id === selectedProgramId) ?? null,
    [programs, selectedProgramId],
  );

  const groupedProgramPlan = useMemo(() => {
    const byTerm = new Map<
      string,
      Map<ProgramPlanRow["group_type"], Map<string, ProgramPlanRow[]>>
    >();

    for (const row of programPlanRows) {
      const term = normalizeTermLabel(row.term_label);
      const groupType: ProgramPlanRow["group_type"] = row.group_type === "optional"
        ? "optional"
        : "mandatory";
      const group = normalizeGroupLabel(row);

      if (!byTerm.has(term)) {
        byTerm.set(term, new Map());
      }
      const typeMap = byTerm.get(term)!;
      if (!typeMap.has(groupType)) {
        typeMap.set(groupType, new Map());
      }
      const groupMap = typeMap.get(groupType)!;
      if (!groupMap.has(group)) {
        groupMap.set(group, []);
      }
      groupMap.get(group)!.push(row);
    }

    return Array.from(byTerm.entries()).map(([term, typeMap]) => ({
      term,
      groupTypes: (["mandatory", "optional"] as const)
        .filter((groupType) => typeMap.has(groupType))
        .map((groupType) => ({
          groupType,
          groups: Array.from(typeMap.get(groupType)!.entries()).map(([group, rows]) => ({
            group,
            rows,
          })),
        })),
    }));
  }, [programPlanRows]);

  return (
    <>
    <div className="admin-panel">
      <div className="admin-panel-header">
        <button className="admin-panel-back-btn" onClick={onBack}>← Back</button>
        <h1 className="admin-panel-title">Admin Panel</h1>
      </div>

      <div className="admin-panel-tabs" role="tablist" aria-label="Admin sections">
        {[
          { key: "pending", label: `Pending (${pending.length})` },
          { key: "lectures", label: `Lectures (${approvedLectures.length})` },
          { key: "programs", label: `Programs (${programs.length})` },
          { key: "courses", label: `Courses (${courses.length})` },
          { key: "mappings", label: "Program-course mappings" },
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

      {error && <p className="admin-panel-error">{error}</p>}
      {loading && <p className="admin-panel-loading">Loading…</p>}

      {!loading && activeTab === "pending" && (
        <section className="admin-panel-section">
          <h2 className="admin-panel-section-title">Pending Approval</h2>
          {pending.length === 0 && (
            <p className="admin-panel-empty">No lectures pending approval.</p>
          )}
          {pending.length > 0 && (
            <table className="admin-panel-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Uploaded by</th>
                  <th>Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pending.map((lecture) => (
                  <tr key={lecture.id}>
                    <td>{lecture.name}</td>
                    <td className="admin-panel-cell--muted">{lecture.uploaded_by ?? "—"}</td>
                    <td className="admin-panel-cell--muted">{formatDate(lecture.created_at)}</td>
                    <td className="admin-panel-actions">
                      <button
                        className="admin-panel-review-btn"
                        onClick={() => setReviewLecture(lecture)}
                      >
                        Review
                      </button>
                      <button
                        className="admin-panel-approve-btn"
                        disabled={actionInFlight === `pending-approve-${lecture.id}`}
                        onClick={() => void handleApprove(lecture.id)}
                      >
                        Approve
                      </button>
                      <button
                        className="admin-panel-reject-btn"
                        disabled={actionInFlight === `pending-reject-${lecture.id}`}
                        onClick={() => void handleReject(lecture.id)}
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {!loading && activeTab === "lectures" && (
        <section className="admin-panel-section">
          <h2 className="admin-panel-section-title">Approved Lectures</h2>
          {approvedLectures.length === 0 && (
            <p className="admin-panel-empty">No approved lectures.</p>
          )}
          {approvedLectures.length > 0 && (
            <table className="admin-panel-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Course</th>
                  <th>Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {approvedLectures.map((lecture) => (
                  <tr key={lecture.id}>
                    <td>{lecture.name}</td>
                    <td className="admin-panel-cell--muted">{lecture.course_display || lecture.course_id}</td>
                    <td className="admin-panel-cell--muted">{formatDate(lecture.created_at)}</td>
                    <td className="admin-panel-actions">
                      <button
                        className="admin-panel-secondary-btn"
                        disabled={actionInFlight === `regen-${lecture.id}`}
                        onClick={() => void handleRegenerateNotes(lecture.id)}
                      >
                        {actionInFlight === `regen-${lecture.id}` ? "Starting..." : "Regenerate notes"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {!loading && activeTab === "programs" && (
        <section className="admin-panel-section">
          <h2 className="admin-panel-section-title">Programs</h2>
          <div className="admin-panel-create-row">
            <input
              className="admin-panel-input"
              placeholder="Code (e.g. CS)"
              value={newProgramCode}
              onChange={(event) => setNewProgramCode(event.target.value)}
            />
            <input
              className="admin-panel-input"
              placeholder="Name"
              value={newProgramName}
              onChange={(event) => setNewProgramName(event.target.value)}
            />
            <button
              className="admin-panel-create-btn"
              disabled={actionInFlight === "create-program" || !newProgramCode.trim() || !newProgramName.trim()}
              onClick={() => void handleCreateProgram()}
            >
              {actionInFlight === "create-program" ? "Creating..." : "Create"}
            </button>
          </div>
          <table className="admin-panel-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {programs.map((program) => (
                <tr key={program.id}>
                  <td>{program.code}</td>
                  <td>{program.name}</td>
                  <td className="admin-panel-cell--muted">{program.is_active ? "Active" : "Inactive"}</td>
                  <td className="admin-panel-actions">
                    <button className="admin-panel-secondary-btn" onClick={() => void handleProgramCode(program)}>Edit code</button>
                    <button className="admin-panel-secondary-btn" onClick={() => void handleProgramRename(program)}>Rename</button>
                    <button className="admin-panel-secondary-btn" onClick={() => void handleToggleProgram(program)}>
                      {program.is_active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {!loading && activeTab === "courses" && (
        <section className="admin-panel-section">
          <h2 className="admin-panel-section-title">Courses</h2>
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
          <table className="admin-panel-table">
            <thead>
              <tr>
                <th>CourseID</th>
                <th>Display</th>
                <th>Name</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {courses.map((course) => (
                <tr key={course.id}>
                  <td>{course.code}</td>
                  <td>{course.display_code || "—"}</td>
                  <td>{course.name}</td>
                  <td className="admin-panel-cell--muted">{course.is_active ? "Active" : "Inactive"}</td>
                  <td className="admin-panel-actions">
                    <button className="admin-panel-secondary-btn" onClick={() => void handleCourseCode(course)}>Edit CourseID</button>
                    <button className="admin-panel-secondary-btn" onClick={() => void handleCourseDisplayCode(course)}>Edit display</button>
                    <button className="admin-panel-secondary-btn" onClick={() => void handleCourseRename(course)}>Rename</button>
                    <button className="admin-panel-secondary-btn" onClick={() => void handleToggleCourse(course)}>
                      {course.is_active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {!loading && activeTab === "mappings" && (
        <section className="admin-panel-section">
          <h2 className="admin-panel-section-title">Program-course mappings</h2>
          <div className="admin-panel-mapping-toolbar">
            <label htmlFor="mapping-program-select">Program</label>
            <ProgramPicker
              id="mapping-program-select"
              value={selectedProgramId}
              programs={programs}
              onChange={setSelectedProgramId}
              disabled={programs.length === 0 || loadingMappings}
              placeholder="Select a program"
              className="program-picker--admin"
            />
          </div>

          {!selectedProgram && (
            <p className="admin-panel-empty">Create a program first to configure mappings.</p>
          )}

          {selectedProgram && (
            <div className="admin-panel-mapping-grid">
              <div className="admin-panel-mapping-list">
                {loadingMappings && <p className="admin-panel-loading">Loading mappings…</p>}
                {!loadingMappings && courses.map((course) => {
                  const isMapped = mappedCourseIds.has(course.id);
                  return (
                    <label key={course.id} className="admin-panel-mapping-item">
                      <input
                        type="checkbox"
                        checked={isMapped}
                        onChange={() => void handleMappingToggle(course)}
                        disabled={actionInFlight === `mapping-${selectedProgram.id}-${course.id}`}
                      />
                      <span>{course.code} - {course.name}</span>
                      {!course.is_active && <span className="admin-panel-badge">Inactive</span>}
                    </label>
                  );
                })}
              </div>

              <div className="admin-panel-plan-view">
                <h3>Program plan</h3>
                {loadingProgramPlan && <p className="admin-panel-loading">Loading plan…</p>}
                {!loadingProgramPlan && groupedProgramPlan.length === 0 && (
                  <p className="admin-panel-empty">No program plan rows available for this program.</p>
                )}
                {!loadingProgramPlan && groupedProgramPlan.length > 0 && (
                  <div className="admin-panel-plan-groups">
                    {groupedProgramPlan.map((termGroup) => (
                      <div key={termGroup.term} className="admin-panel-plan-term">
                        <h4>{termGroup.term}</h4>
                        {termGroup.groupTypes.map((typeGroup) => (
                          <div key={`${termGroup.term}-${typeGroup.groupType}`} className="admin-panel-plan-subgroup">
                            <h5>{formatGroupType(typeGroup.groupType)}</h5>
                            {typeGroup.groups.map((group) => (
                              <div key={`${termGroup.term}-${typeGroup.groupType}-${group.group}`}>
                                <h6>{group.group}</h6>
                                <ul>
                                  {group.rows.map((row) => (
                                    <li key={row.id}>
                                      <span className="admin-panel-plan-course-name">{row.course_name_sv}</span>
                                      <span className="admin-panel-plan-course-meta">
                                        {row.course_code ? `${row.course_code} · ` : ""}
                                        {row.group_type}
                                      </span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      )}

      {!loading && activeTab === "catalog" && (
        <section className="admin-panel-section">
          <h2 className="admin-panel-section-title">Catalog sync</h2>
          <p className="admin-panel-cell--muted admin-panel-sync-copy">
            Syncs current Stockholm University DSV catalog into programs, courses, mappings, and plan rows.
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
                <p>Standalone: <strong>{catalogResult.standalone_count}</strong></p>
                <p>Programs: <strong>{catalogResult.program_count}</strong></p>
                <p>Program-course rows: <strong>{catalogResult.program_course_count}</strong></p>
                <p>Plan rows written: <strong>{catalogResult.program_plan_rows_written}</strong></p>
                <p>Programs +/{catalogResult.programs_created} ~/{catalogResult.programs_updated} -/{catalogResult.programs_deactivated}</p>
                <p>Courses +/{catalogResult.courses_created} ~/{catalogResult.courses_updated} -/{catalogResult.courses_deactivated}</p>
                <p>Mappings +/{catalogResult.mappings_added} -/{catalogResult.mappings_removed}</p>
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
          onApproved={(id) => {
            setPending((prev) => prev.filter((l) => l.id !== id));
            setReviewLecture(null);
          }}
          onRejected={(id) => {
            setPending((prev) => prev.filter((l) => l.id !== id));
            setReviewLecture(null);
          }}
          onClose={() => setReviewLecture(null)}
        />
      )}
      {regenerateJobStatus && (
        <RegenerateNotesModal
          lectureTitle={approvedLectures.find(l => l.id === regenerateJobStatus.lecture_id)?.name ?? "Unknown"}
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
