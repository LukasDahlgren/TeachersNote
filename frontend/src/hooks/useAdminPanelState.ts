import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  createCourse,
  getCourses,
  getLectures,
  getPendingLectures,
  rejectLecture,
  runCatalogSync,
  startRegenerateNotesJob,
  trashLecture,
  updateCourse,
} from "../api";
import type {
  CatalogSyncResult,
  Course,
  RegenerateNotesJobStatus,
  TeachersNoteSummary,
} from "../types";

export type AdminDialogState =
  | { type: "confirm-reject"; id: number }
  | { type: "confirm-delete"; lecture: { id: number; name: string } }
  | { type: "edit-course-name"; course: Course }
  | { type: "edit-course-code"; course: Course }
  | { type: "edit-course-display-code"; course: Course }
  | null;

export type AdminTab = "lectures" | "courses" | "catalog";

export function useAdminPanelState() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<AdminTab>("lectures");
  const [courses, setCourses] = useState<Course[]>([]);
  const [approvedLectures, setApprovedLectures] = useState<TeachersNoteSummary[]>([]);

  const [reviewLecture, setReviewLecture] = useState<TeachersNoteSummary | null>(null);
  const [regenerateJobStatus, setRegenerateJobStatus] = useState<RegenerateNotesJobStatus | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState<string | null>(null);
  const [dialog, setDialog] = useState<AdminDialogState>(null);

  const [newCourseCode, setNewCourseCode] = useState("");
  const [newCourseDisplayCode, setNewCourseDisplayCode] = useState("");
  const [newCourseName, setNewCourseName] = useState("");
  const [showCreateCourse, setShowCreateCourse] = useState(false);

  const [catalogSnapshotDate, setCatalogSnapshotDate] = useState("");
  const [catalogDryRun, setCatalogDryRun] = useState(false);
  const [catalogResult, setCatalogResult] = useState<CatalogSyncResult | null>(null);

  const [lectureSearch, setLectureSearch] = useState("");
  const [courseSearch, setCourseSearch] = useState("");
  const [openLectureActionsFor, setOpenLectureActionsFor] = useState<number | null>(null);
  const [openCourseActionsFor, setOpenCourseActionsFor] = useState<number | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [, courseData, lecturesData] = await Promise.all([
        getPendingLectures(),
        getCourses(),
        getLectures(),
      ]);
      setCourses(courseData);
      setApprovedLectures(lecturesData.filter((lecture) => !lecture.is_deleted && !lecture.is_archived));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleReject(id: number) {
    setActionInFlight(`pending-reject-${id}`);
    try {
      await rejectLecture(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject lecture.");
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
      setShowCreateCourse(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create course.");
    } finally {
      setActionInFlight(null);
    }
  }

  async function handleCourseRename(course: Course, nextName: string) {
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

  async function handleCourseCode(course: Course, nextCode: string) {
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

  async function handleCourseDisplayCode(course: Course, nextDisplayCode: string) {
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

  async function handleDeleteLecture(lecture: { id: number; name: string }) {
    const key = `lecture-delete-${lecture.id}`;
    setActionInFlight(key);
    setError(null);
    try {
      await trashLecture(lecture.id);
      setApprovedLectures((previous) => previous.filter((item) => item.id !== lecture.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete lecture.");
    } finally {
      setActionInFlight(null);
    }
  }

  function handleOpenLecture(lectureId: number) {
    navigate(`/lectures/${lectureId}`);
  }

  const filteredLectures = useMemo(() => {
    const query = lectureSearch.trim().toLowerCase();
    if (!query) return approvedLectures;
    return approvedLectures.filter((lecture) =>
      lecture.name.toLowerCase().includes(query)
      || (lecture.course_display ?? "").toLowerCase().includes(query)
      || (lecture.course_id ?? "").toLowerCase().includes(query),
    );
  }, [approvedLectures, lectureSearch]);

  const filteredCourses = useMemo(() => {
    const query = courseSearch.trim().toLowerCase();
    if (!query) return courses;
    return courses.filter((course) =>
      course.code.toLowerCase().includes(query)
      || (course.display_code ?? "").toLowerCase().includes(query)
      || course.name.toLowerCase().includes(query),
    );
  }, [courseSearch, courses]);

  return {
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
  };
}
