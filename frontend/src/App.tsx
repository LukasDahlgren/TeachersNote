import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { Navigate, Route, Routes, useLocation, useMatch, useNavigate } from "react-router-dom";
import {
  ApiError,
  archiveLecture,
  checkHealth,
  getLectures,
  getLecture,
  getMe,
  getMyLectures,
  getProfile,
  getProcessJob,
  logout,
  saveLecture,
  startProcessJob,
  findBestLectureWithNotesByExactName,
  trashLecture,
  unarchiveLecture,
  unsaveLecture,
} from "./api";
import ProcessingConsoleOverlay from "./components/ProcessingConsoleOverlay";
import Sidebar from "./components/Sidebar";
import ErrorBoundary from "./components/ErrorBoundary";
import Homepage from "./components/Homepage";
import AllLecturesPlaceholder from "./components/AllLecturesPlaceholder";
import AdminPanel from "./components/AdminPanel";
import LoginPage from "./components/LoginPage";
import NewLectureOverlay from "./components/NewLectureOverlay";
import SignupPage from "./components/SignupPage";
import ProfilePage from "./components/ProfilePage";
import WorkspaceRouteContent from "./components/WorkspaceRouteContent";
import { useProcessJobController } from "./hooks/useProcessJobController";
import { useRouteMotion } from "./hooks/useRouteMotion";
import { formatLectureDisplayName } from "./utils/lectureNaming";
import {
  type AuthUser,
  type TeachersNoteSummary,
  type RegenerateNotesJobStatus,
  type UploadRecordingInput,
  type UploadProcessJobStatus,
  type StudentProfile,
} from "./types";
import type { MainView, LectureData } from "./appShellTypes";

const ACTIVE_PROCESS_JOB_STORAGE_KEY = "teachers-note.active-process-job-id";
const LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY = "lecture-summary.active-process-job-id";
const DEMO_LECTURE_NAME = "IB133N-lecture-14-2026";
const PROCESS_DETAIL_RETRY_DELAYS_MS = [700, 1300, 2000];
const PROCESS_STATUS_POLL_MS = 5000;
const DEMO_UPLOAD_STAGES: Array<{ label: string; stage: string; delayMs: number }> = [
  { label: "📄 Parsing slides...", stage: "parse_slides", delayMs: 450 },
  { label: "📄 Extracted 27 slides.", stage: "parse_slides", delayMs: 900 },
  { label: "☁️ Transcribing recording...", stage: "transcribe", delayMs: 1400 },
  { label: "🔗 Aligning transcript to slides...", stage: "align", delayMs: 600 },
  { label: "✨ Enriching 27 slides...", stage: "enrich", delayMs: 1100 },
];

type ProcessBanner = { kind: "success" | "error" | "info"; text: string };
type ProcessToast = { kind: "success" | "error" | "info"; text: string; lectureId?: number };
type OverlayAnchorRect = {
  top: number;
  right: number;
  bottom: number;
  left: number;
  width: number;
  height: number;
};
type LectureRefreshResult = { ok: true } | { ok: false; error: string };

function isWorkspacePath(pathname: string): boolean {
  return pathname === "/workspace" || pathname.startsWith("/lectures/");
}

function rectSnapshot(rect: DOMRect): OverlayAnchorRect {
  return {
    top: rect.top,
    right: rect.right,
    bottom: rect.bottom,
    left: rect.left,
    width: rect.width,
    height: rect.height,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function formatProcessStage(stage: string): string {
  return stage.replace(/_/g, " ");
}

function toErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function App() {
  const [mainView, setMainView] = useState<MainView>({ view: "empty" });
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [lectures, setLectures] = useState<TeachersNoteSummary[]>([]);
  const [savedLectures, setSavedLectures] = useState<TeachersNoteSummary[]>([]);
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [lecturesLoading, setLecturesLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [processBanner, setProcessBanner] = useState<ProcessBanner | null>(null);
  const [regeneratingNotes, setRegeneratingNotes] = useState(false);
  const [regenBanner, setRegenBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [regenJob, setRegenJob] = useState<RegenerateNotesJobStatus | null>(null);
  const [savePending, setSavePending] = useState(false);
  const [saveBanner, setSaveBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [archivePending, setArchivePending] = useState(false);
  const [archiveBanner, setArchiveBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [processToast, setProcessToast] = useState<ProcessToast | null>(null);
  const [processOverlayDismissed, setProcessOverlayDismissed] = useState(false);
  const [processOverlayDoneData, setProcessOverlayDoneData] = useState<{
    lectureId: number;
    downloadUrl: string | null;
  } | null>(null);
  const [isNewLectureOverlayOpen, setIsNewLectureOverlayOpen] = useState(false);
  const [newLectureButtonRect, setNewLectureButtonRect] = useState<OverlayAnchorRect | null>(null);
  const [demoPreviewActive, setDemoPreviewActive] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletePending, setDeletePending] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null);
  type AuthState = "loading" | "unauthenticated" | "authenticated";
  const [authState, setAuthState] = useState<AuthState>("loading");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authView, setAuthView] = useState<"login" | "signup">("login");
  const isAdmin = authUser?.is_admin ?? false;
  const [chatOpen, setChatOpen] = useState(false);
  const [chatPrefill, setChatPrefill] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("sidebar-collapsed") === "true"
  );

  function toggleSidebar() {
    setSidebarCollapsed((c) => {
      const next = !c;
      localStorage.setItem("sidebar-collapsed", String(next));
      return next;
    });
  }

  const demoRegenRunRef = useRef(0);
  const demoRunRef = useRef(0);
  const newLectureButtonElementRef = useRef<HTMLButtonElement | null>(null);
  const processControllerRef = useRef<ReturnType<typeof useProcessJobController> | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const locationPathRef = useRef(location.pathname);
  const routeMotionKey = authState === "unauthenticated"
    ? `auth:${authView}`
    : location.pathname;
  const routeMotion = useRouteMotion(location, { transitionKey: routeMotionKey });
  const lectureRouteMatch = useMatch("/lectures/:lectureId");
  const lectureRouteIdParam = lectureRouteMatch?.params.lectureId ?? null;

  useEffect(() => {
    locationPathRef.current = location.pathname;
  }, [location.pathname]);

  const updateNewLectureButtonRect = useCallback(() => {
    if (!newLectureButtonElementRef.current) return;
    setNewLectureButtonRect(rectSnapshot(newLectureButtonElementRef.current.getBoundingClientRect()));
  }, []);

  const handleNewLectureButtonRef = useCallback((el: HTMLButtonElement | null) => {
    newLectureButtonElementRef.current = el;
    if (!el) return;
    setNewLectureButtonRect(rectSnapshot(el.getBoundingClientRect()));
  }, []);

  const closeNewLectureOverlay = useCallback(() => {
    setIsNewLectureOverlayOpen(false);
  }, []);

  const openNewLectureOverlay = useCallback(() => {
    updateNewLectureButtonRect();
    setIsNewLectureOverlayOpen(true);
  }, [updateNewLectureButtonRect]);

  const fetchLectures = useCallback(async (): Promise<LectureRefreshResult> => {
    setLecturesLoading(true);
    try {
      const [catalog, saved] = await Promise.all([getLectures(), getMyLectures()]);
      setLectures(catalog);
      setSavedLectures(saved);
      return { ok: true };
    } catch (err) {
      const message = toErrorMessage(err);
      console.warn("Failed to refresh lectures list:", message);
      return { ok: false, error: message };
    } finally {
      setLecturesLoading(false);
    }
  }, [isAdmin]);

  const fetchProfile = useCallback(async () => {
    try {
      const nextProfile = await getProfile();
      setProfile(nextProfile);
    } catch (err) {
      console.warn("Failed to refresh profile:", toErrorMessage(err));
    }
  }, []);

  useEffect(() => {
    checkHealth().then(setBackendOnline);
  }, []);

  useEffect(() => {
    if (authState !== "authenticated") return;
    void fetchLectures();
    void fetchProfile();
  }, [authState, fetchLectures, fetchProfile]);

  useEffect(() => {
    getMe()
      .then((user) => {
        setAuthUser(user);
        setAuthState("authenticated");
      })
      .catch(() => {
        logout();
        setAuthState("unauthenticated");
      });
  }, []);

  useEffect(() => {
    if (!isNewLectureOverlayOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setIsNewLectureOverlayOpen(false);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isNewLectureOverlayOpen]);

  useEffect(() => {
    if (!isNewLectureOverlayOpen) return;
    updateNewLectureButtonRect();

    const update = () => {
      updateNewLectureButtonRect();
    };

    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [isNewLectureOverlayOpen, updateNewLectureButtonRect]);

  useEffect(() => {
    setIsNewLectureOverlayOpen(false);
    setProcessToast(null);
  }, [location.pathname]);

  useEffect(() => {
    if (!processToast) return;
    const timerId = window.setTimeout(() => {
      setProcessToast(null);
    }, 7000);

    return () => {
      window.clearTimeout(timerId);
    };
  }, [processToast]);

  const resetRegenerationUi = useCallback(() => {
    demoRegenRunRef.current += 1;
    setRegeneratingNotes(false);
    setRegenBanner(null);
    setRegenJob(null);
    setSaveBanner(null);
    setArchiveBanner(null);
  }, []);

  const fetchLectureWithRetry = useCallback(async (lectureId: number): Promise<LectureData> => {
    let lastError: unknown = null;
    for (let attempt = 0; attempt <= PROCESS_DETAIL_RETRY_DELAYS_MS.length; attempt += 1) {
      try {
        return await getLecture(lectureId);
      } catch (err) {
        lastError = err;
        if (attempt >= PROCESS_DETAIL_RETRY_DELAYS_MS.length) {
          break;
        }
        await sleep(PROCESS_DETAIL_RETRY_DELAYS_MS[attempt]);
      }
    }
    throw lastError instanceof Error ? lastError : new Error(String(lastError));
  }, []);

  const failProcessJob = useCallback((message: string) => {
    processControllerRef.current?.reset(false);
    const workspaceContext = isWorkspacePath(locationPathRef.current);
    if (workspaceContext) {
      setProcessBanner({ kind: "error", text: message });
      setMainView({ view: "upload", loading: false, error: message });
    } else {
      setProcessBanner(null);
      setMainView((prev) => (
        prev.view === "upload" ? { ...prev, loading: false, error: undefined } : prev
      ));
      setProcessToast({ kind: "error", text: message });
    }
  }, []);

  const finishProcessJob = useCallback(async (status: UploadProcessJobStatus) => {
    processControllerRef.current?.reset(false);

    const workspaceContext = isWorkspacePath(locationPathRef.current);
    const lectureId = status.lecture_id;
    if (!lectureId) {
      const missingIdMessage = "Processing completed but lecture id was missing.";
      if (workspaceContext) {
        setMainView({ view: "upload", loading: false, error: missingIdMessage });
      } else {
        setMainView((prev) => (
          prev.view === "upload" ? { ...prev, loading: false, error: undefined } : prev
        ));
        setProcessToast({ kind: "error", text: missingIdMessage });
      }
      return;
    }

    const successText = status.reused_existing
      ? "Existing lecture unlocked."
      : "Lecture processed successfully.";
    const refreshResult = await fetchLectures();
    let completionWarning: string | null = null;
    if (!refreshResult.ok) {
      completionWarning = `Lecture was saved, but refreshing Saved lectures failed (${refreshResult.error}).`;
    }

    if (!workspaceContext) {
      setSelectedId(lectureId);
      setMainView((prev) => (
        prev.view === "upload" ? { ...prev, loading: false, error: undefined } : prev
      ));
      setProcessBanner(null);
      setProcessToast({
        kind: completionWarning ? "error" : "success",
        text: completionWarning ?? successText,
        lectureId,
      });
      setProcessOverlayDoneData({ lectureId, downloadUrl: null });
      return;
    }

    try {
      const data = await fetchLectureWithRetry(lectureId);
      setSelectedId(lectureId);
      setMainView({ view: "results", data, activeSlide: 0, lectureId });
      setProcessBanner(completionWarning ? { kind: "error", text: completionWarning } : null);
      setProcessToast(null);
      setProcessOverlayDoneData({ lectureId, downloadUrl: data.download_url ?? null });
    } catch (err) {
      const detailError = toErrorMessage(err);
      const refreshSuffix = refreshResult.ok
        ? ""
        : ` Also, refreshing Saved lectures failed (${refreshResult.error || "unknown error"}).`;
      const message = (
        "Processing finished and lecture was saved, but we could not open it automatically. "
        + "Select it from Saved lectures and try again."
        + refreshSuffix
      );
      setProcessBanner({ kind: "info", text: message });
      setMainView({ view: "upload", loading: false, error: undefined });
      console.warn(`Failed to open lecture ${lectureId} after completion:`, detailError);
    }
  }, [fetchLectureWithRetry, fetchLectures]);

  const processController = useProcessJobController({
    activeProcessJobStorageKey: ACTIVE_PROCESS_JOB_STORAGE_KEY,
    legacyActiveProcessJobStorageKey: LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY,
    onDone: finishProcessJob,
    onError: failProcessJob,
    onLectureAdded: useCallback(() => {
      void fetchLectures();
    }, [fetchLectures]),
    pollMs: PROCESS_STATUS_POLL_MS,
  });
  processControllerRef.current = processController;

  const {
    appendProcessChat,
    attachToJob: subscribeToProcessJob,
    job: processJob,
    liveEnrichedSlides,
    persistJobId,
    processChat,
    reset: resetProcessController,
    resumePersistedJob,
    setJob: setProcessJob,
    setProcessChat,
    setUploadLoadingLabel,
    uploadLoadingLabel,
  } = processController;

  const resetProcessUi = useCallback((clearPersisted = true) => {
    resetProcessController(clearPersisted);
    setProcessBanner(null);
    setProcessOverlayDismissed(false);
    setProcessOverlayDoneData(null);
  }, [resetProcessController]);

  useEffect(() => {
    const storedJobId = window.localStorage.getItem(ACTIVE_PROCESS_JOB_STORAGE_KEY)?.trim()
      || window.localStorage.getItem(LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY)?.trim();
    if (!storedJobId) return;

    setMainView({ view: "upload", loading: true });
    void resumePersistedJob().catch((error) => {
      console.warn("Failed to resume persisted process job:", toErrorMessage(error));
    });
  }, [resumePersistedJob]);

  const handleRunDemo = useCallback(async () => {
    const runId = demoRunRef.current + 1;
    demoRunRef.current = runId;

    setDemoPreviewActive(true);
    setProcessToast(null);
    resetRegenerationUi();
    resetProcessUi(true);
    setProcessBanner(null);
    setSelectedId(null);
    setMainView({ view: "upload", loading: true });

    try {
      // Simulate progress through stages with increasing percentages
      const stageProgressMap: Record<string, { start: number; end: number }> = {
        "📄 Parsing slides...": { start: 0, end: 10 },
        "📄 Extracted 27 slides.": { start: 10, end: 22 },
        "☁️ Transcribing recording...": { start: 22, end: 55 },
        "🔗 Aligning transcript to slides...": { start: 55, end: 70 },
        "✨ Enriching 27 slides...": { start: 70, end: 100 },
      };

      for (const stage of DEMO_UPLOAD_STAGES) {
        if (demoRunRef.current !== runId) return;

        const progressRange = stageProgressMap[stage.label];
        const startProgress = progressRange?.start ?? 0;
        const endProgress = progressRange?.end ?? 100;
        const stepSize = (endProgress - startProgress) / Math.max(1, Math.ceil(stage.delayMs / 100));

        // Add a chat entry for this stage
        appendProcessChat({
          job_id: `demo-${Date.now()}`,
          status: "running",
          current_stage: stage.stage,
          progress_pct: startProgress,
          lecture_id: null,
          total_slides: null,
          pdf_url: null,
          error: null,
          updated_at: new Date().toISOString(),
          message: stage.label,
        }, "log");

        // Simulate per-slide enrichment progress
        if (stage.stage === "enrich") {
          const totalSlides = 27;
          for (let slide = 1; slide <= totalSlides; slide++) {
            if (demoRunRef.current !== runId) return;
            await sleep(stage.delayMs / totalSlides);
            appendProcessChat({
              job_id: `demo-${Date.now()}`,
              status: "running",
              current_stage: "enrich",
              progress_pct: 70 + Math.round((slide / totalSlides) * 20),
              lecture_id: null,
              total_slides: null,
              pdf_url: null,
              error: null,
              updated_at: new Date().toISOString(),
              message: `✅ Slide ${slide} done (${slide}/${totalSlides})`,
            }, "log");
          }
        }

        // Animate progress during this stage
        for (let progress = startProgress; progress <= endProgress; progress += stepSize) {
          if (demoRunRef.current !== runId) return;
          const currentProgress = Math.min(Math.round(progress), 100);
          setProcessJob({
            job_id: `demo-${Date.now()}`,
            status: "running",
            current_stage: stage.stage,
            progress_pct: currentProgress,
            lecture_id: null,
            total_slides: null,
            pdf_url: null,
            error: null,
            updated_at: new Date().toISOString(),
          });
          setUploadLoadingLabel(`Processing: ${formatProcessStage(stage.stage)} (${currentProgress}%)`);
          await sleep(100);
        }

        // Ensure we reach the end percentage
        if (demoRunRef.current === runId) {
          setProcessJob({
            job_id: `demo-${Date.now()}`,
            status: "running",
            current_stage: stage.stage,
            progress_pct: endProgress,
            lecture_id: null,
            total_slides: null,
            pdf_url: null,
            error: null,
            updated_at: new Date().toISOString(),
          });
          setUploadLoadingLabel(`Processing: ${formatProcessStage(stage.stage)} (${endProgress}%)`);
        }
      }

      if (demoRunRef.current !== runId) return;

      const selectedDemo = await findBestLectureWithNotesByExactName(DEMO_LECTURE_NAME);
      if (!selectedDemo) {
        setDemoPreviewActive(false);
        setMainView({
          view: "upload",
          loading: false,
          error: `No lecture named ${DEMO_LECTURE_NAME} with notes was found. Process one and try again.`,
        });
        return;
      }

      const lectureId = selectedDemo.lecture.lecture_id ?? selectedDemo.summary.id;
      const lectureName = selectedDemo.lecture.name || selectedDemo.summary.name;
      const lectureData: LectureData = {
        ...selectedDemo.lecture,
        lecture_id: lectureId,
        name: lectureName,
        is_archived: selectedDemo.summary.is_archived,
        is_saved: selectedDemo.summary.is_saved,
      };

      setSelectedId(selectedDemo.summary.id);
      await fetchLectures();
      if (demoRunRef.current !== runId) return;
      setMainView({ view: "results", data: lectureData, activeSlide: 0, lectureId: selectedDemo.summary.id });
    } catch (err) {
      setDemoPreviewActive(false);
      setMainView({
        view: "upload",
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      if (demoRunRef.current === runId) {
        setUploadLoadingLabel("");
        setProcessJob(null);
        setMainView((prev) => (prev.view === "upload" ? { ...prev, loading: false } : prev));
      }
    }
  }, [appendProcessChat, fetchLectures, resetProcessUi, resetRegenerationUi]);

  async function handleSubmit(pdf: File, recording: UploadRecordingInput, courseContext: string | null = null, lectureName = "") {
    demoRunRef.current += 1;
    setDemoPreviewActive(false);
    setProcessToast(null);
    resetRegenerationUi();
    resetProcessUi(true);
    setProcessBanner(null);
    setMainView({ view: "upload", loading: true });
    try {
      const job = await startProcessJob(pdf, recording, undefined, courseContext, lectureName || undefined);
      setSelectedId(null);
      setProcessJob(job);
      setUploadLoadingLabel(`Processing: ${formatProcessStage(job.current_stage)} (${job.progress_pct}%)`);
      persistJobId(job.job_id);

      if (job.status === "done") {
        await finishProcessJob(job);
        return;
      }
      if (job.status === "error") {
        failProcessJob(job.error || "Upload processing failed.");
        return;
      }
      subscribeToProcessJob(job.job_id, 0);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const activeJobId = (err.data as { active_job_id?: string } | null)?.active_job_id;
        if (activeJobId) {
          try {
            const snapshot = await getProcessJob(activeJobId);
            setProcessJob(snapshot);
            setProcessChat([]);
            setUploadLoadingLabel(`Processing: ${formatProcessStage(snapshot.current_stage)} (${snapshot.progress_pct}%)`);
            persistJobId(activeJobId);

            if (snapshot.status === "done") {
              await finishProcessJob(snapshot);
              return;
            }
            if (snapshot.status === "error") {
              failProcessJob(snapshot.error || "Upload processing failed.");
              return;
            }
            subscribeToProcessJob(activeJobId, 0);
            return;
          } catch (snapshotErr) {
            failProcessJob(snapshotErr instanceof Error ? snapshotErr.message : String(snapshotErr));
            return;
          }
        }
      }

      failProcessJob(toErrorMessage(err));
    }
  }

  const loadLectureIntoWorkspace = useCallback(async (id: number) => {
    demoRunRef.current += 1;
    setDemoPreviewActive(false);
    setProcessToast(null);
    setIsNewLectureOverlayOpen(false);
    resetRegenerationUi();
    const isProcessingLecture = (
      processJob?.lecture_id === id &&
      (processJob?.status === "queued" || processJob?.status === "running")
    );
    if (!isProcessingLecture) {
      resetProcessUi(false);
    }
    setProcessBanner(null);
    setSaveBanner(null);
    setArchiveBanner(null);
    setSelectedId(id);
    setMainView({ view: "upload", loading: true });
    try {
      const data = await getLecture(id);
      setMainView({ view: "results", data, activeSlide: 0, lectureId: id });
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
        setSelectedId(null);
        setMainView({ view: "empty" });
        navigate("/workspace", { replace: true });
      } else {
        setMainView({ view: "upload", loading: false, error: String(err) });
      }
    }
  }, [navigate, resetProcessUi, resetRegenerationUi]);

  const handleSelectLecture = useCallback((id: number) => {
    setIsNewLectureOverlayOpen(false);
    setProcessToast(null);
    setProcessBanner(null);
    setSelectedId(id);
    if (location.pathname === `/lectures/${id}`) {
      void loadLectureIntoWorkspace(id);
      return;
    }
    navigate(`/lectures/${id}`);
  }, [loadLectureIntoWorkspace, location.pathname, navigate]);

  const handleNewLecture = useCallback(() => {
    demoRunRef.current += 1;
    setDemoPreviewActive(false);
    if (!processJob || processJob.status === "done" || processJob.status === "error") {
      resetProcessUi(true);
    }
    setProcessBanner(null);
    setProcessToast(null);
    openNewLectureOverlay();
  }, [openNewLectureOverlay, processJob, resetProcessUi]);

  const handleGoHome = useCallback(() => {
    demoRunRef.current += 1;
    setDemoPreviewActive(false);
    setProcessToast(null);
    setIsNewLectureOverlayOpen(false);
    navigate("/");
  }, [navigate]);

  const handleLogin = useCallback((user: AuthUser) => {
    setAuthUser(user);
    setAuthState("authenticated");
  }, []);

  const handleLogout = useCallback(() => {
    logout();
    setAuthUser(null);
    setAuthState("unauthenticated");
    setLectures([]);
    setSavedLectures([]);
    setProfile(null);
    setProcessToast(null);
    setIsNewLectureOverlayOpen(false);
    setMainView({ view: "empty" });
  }, []);

  useEffect(() => {
    if (location.pathname === "/workspace" && mainView.view === "empty") {
      setMainView({ view: "upload", loading: false });
    }
  }, [location.pathname, mainView.view]);

  useEffect(() => {
    if (!deleteDialogOpen || deletePending) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setDeleteDialogOpen(false);
      setDeleteTarget(null);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [deleteDialogOpen, deletePending]);

  useEffect(() => {
    if (!lectureRouteIdParam) return;
    const parsedId = Number(lectureRouteIdParam);

    if (!Number.isInteger(parsedId) || parsedId <= 0) {
      resetRegenerationUi();
      resetProcessUi(false);
      setSaveBanner(null);
      setArchiveBanner(null);
      setProcessBanner(null);
      setSelectedId(null);
      setMainView({ view: "upload", loading: false, error: "Invalid lecture id." });
      navigate("/workspace", { replace: true });
      return;
    }

    void loadLectureIntoWorkspace(parsedId);
  }, [
    lectureRouteIdParam,
    loadLectureIntoWorkspace,
    navigate,
    resetProcessUi,
    resetRegenerationUi,
  ]);

  async function handleToggleArchive() {
    if (mainView.view !== "results" || demoPreviewActive) return;

    const lectureId = mainView.lectureId ?? mainView.data.lecture_id;
    if (!lectureId) {
      setArchiveBanner({ kind: "error", text: "Cannot archive because lecture id is missing." });
      return;
    }

    const shouldArchive = !mainView.data.is_archived;
    setArchivePending(true);
    setSaveBanner(null);
    setArchiveBanner(null);

    try {
      const response = shouldArchive
        ? await archiveLecture(lectureId)
        : await unarchiveLecture(lectureId);

      setMainView((prev) => (
        prev.view === "results"
          ? {
            ...prev,
            data: {
              ...prev.data,
              is_archived: response.is_archived,
              download_url: response.download_url,
              pdf_url: response.pdf_url,
            },
            lectureId,
          }
          : prev
      ));

      await fetchLectures();
      setArchiveBanner({
        kind: "success",
        text: response.is_archived ? "Lecture archived." : "Lecture unarchived.",
      });
    } catch (err) {
      setArchiveBanner({
        kind: "error",
        text: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setArchivePending(false);
    }
  }

  async function handleToggleSaved() {
    if (mainView.view !== "results" || demoPreviewActive) return;

    const lectureId = mainView.lectureId ?? mainView.data.lecture_id;
    if (!lectureId) {
      setSaveBanner({ kind: "error", text: "Cannot update saved status because lecture id is missing." });
      return;
    }

    const currentlySaved = Boolean(mainView.data.is_saved);
    setSavePending(true);
    setArchiveBanner(null);
    setSaveBanner(null);

    try {
      const response = currentlySaved
        ? await unsaveLecture(lectureId)
        : await saveLecture(lectureId);

      setMainView((prev) => (
        prev.view === "results"
          ? {
            ...prev,
            data: {
              ...prev.data,
              is_saved: response.is_saved,
            },
            lectureId,
          }
          : prev
      ));

      await fetchLectures();
      setSaveBanner({
        kind: "success",
        text: response.is_saved ? "Lecture saved." : "Removed from Saved lectures.",
      });
    } catch (err) {
      setSaveBanner({
        kind: "error",
        text: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSavePending(false);
    }
  }

  function openDeleteDialog() {
    if (!isWorkspaceRoute || mainView.view !== "results" || demoPreviewActive) return;
    const lectureId = mainView.lectureId ?? mainView.data.lecture_id;
    if (!lectureId) return;

    const lectureDisplayName = formatLectureDisplayName(mainView.data).trim();
    setDeleteTarget({
      id: lectureId,
      name: lectureDisplayName || "this lecture",
    });
    setDeleteDialogOpen(true);
  }

  function cancelDeleteDialog() {
    if (deletePending) return;
    setDeleteDialogOpen(false);
    setDeleteTarget(null);
  }

  async function confirmDeleteDialog() {
    if (!deleteTarget) return;
    setDeletePending(true);

    try {
      await trashLecture(deleteTarget.id);
      await fetchLectures();
      setSelectedId(null);
      setMainView({ view: "empty" });
      navigate("/");
    } catch (err) {
      setArchiveBanner({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setDeletePending(false);
      setDeleteDialogOpen(false);
      setDeleteTarget(null);
    }
  }

  const activeSlideComputed = useMemo(() => {
    if (mainView.view !== "results") return null;
    const { data, activeSlide, lectureId } = mainView;

    const isProcessingLecture = (
      lectureId !== undefined &&
      lectureId === processJob?.lecture_id &&
      (processJob?.status === "queued" || processJob?.status === "running")
    );

    const effectiveEnhanced = isProcessingLecture && liveEnrichedSlides.length > 0
      ? liveEnrichedSlides
      : data.enhanced;

    const alignment = data.alignment.find(a => a.slide === activeSlide + 1);
    const segments = alignment
      ? data.transcript.slice(alignment.start_segment, alignment.end_segment + 1)
      : [];
    const isEnriching = isProcessingLecture && processJob?.current_stage === "enrich";
    return { data: { ...data, enhanced: effectiveEnhanced }, activeSlide, segments, isEnriching };
  }, [mainView, liveEnrichedSlides, processJob]);

  const navigateSlide = useCallback((delta: number) => {
    setMainView((prev) => {
      if (prev.view !== "results") return prev;
      const totalSlides = prev.data.slides.length;
      if (totalSlides <= 0) return prev;

      const nextSlide = Math.max(0, Math.min(prev.activeSlide + delta, totalSlides - 1));
      if (nextSlide === prev.activeSlide) return prev;

      return {
        ...prev,
        activeSlide: nextSlide,
      };
    });
  }, []);

  const onPrev = useCallback(() => {
    navigateSlide(-1);
  }, [navigateSlide]);

  const onNext = useCallback(() => {
    navigateSlide(1);
  }, [navigateSlide]);

  useEffect(() => {
    if (mainView.view !== "results") return;

    const isEditableTarget = (target: EventTarget | null): boolean => {
      if (!(target instanceof HTMLElement)) return false;
      if (target.isContentEditable) return true;
      if (target.closest("input, textarea, select, [contenteditable='true']")) return true;
      return false;
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isEditableTarget(event.target)) return;

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        navigateSlide(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        navigateSlide(1);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [mainView.view, navigateSlide]);

  const regenerationProgressText = useMemo(() => {
    if (!regeneratingNotes) return "";
    const total = regenJob?.total_slides ?? 0;
    if (total === 0) return "Regenerating notes: Slide 0 of 0";

    const completed = Math.max(0, regenJob?.completed_slides ?? 0);
    const position = Math.min(completed + 1, total);
    if (regenJob?.current_slide != null) {
      return `Regenerating notes: Slide ${regenJob.current_slide} (${position} of ${total})`;
    }
    return `Regenerating notes: Slide ${position} of ${total}`;
  }, [regenJob, regeneratingNotes]);

  const sidebarSavedLectures = useMemo(
    () => savedLectures.filter((lecture) => !lecture.is_archived),
    [savedLectures],
  );

  const sidebarArchivedLectures = useMemo(
    () => (
      isAdmin
        ? lectures.filter((lecture) => lecture.is_archived)
        : savedLectures.filter((lecture) => lecture.is_archived)
    ),
    [isAdmin, lectures, savedLectures],
  );

  const consoleEntries = useMemo(() => {
    type Entry = { id: number; message: string; done: boolean; stage: string };
    const entries: Entry[] = [];

    for (const chat of processChat) {
      // Merge per-slide messages into the enriching line counter
      const slideMatch = chat.message.match(/✅ Slide \d+ done \((\d+)\/(\d+)\)/);
      if (slideMatch) {
        const current = parseInt(slideMatch[1], 10);
        const total = parseInt(slideMatch[2], 10);
        let enrichIdx = -1;
        for (let i = entries.length - 1; i >= 0; i--) {
          if (entries[i].stage === "enrich") { enrichIdx = i; break; }
        }
        if (enrichIdx >= 0) {
          entries[enrichIdx] = {
            ...entries[enrichIdx],
            message: `✨ Enriching slides... (${current}/${total})`,
            done: current === total,
          };
        }
        continue;
      }

      if (chat.stage === "enrich") continue;

      // Mark previous stage entries as done when stage changes
      if (entries.length > 0) {
        const prevStage = entries[entries.length - 1].stage;
        if (prevStage !== chat.stage) {
          for (let i = entries.length - 1; i >= 0 && entries[i].stage === prevStage; i--) {
            entries[i] = { ...entries[i], done: true };
          }
        }
      }

      entries.push({ id: chat.eventId, message: chat.message, done: false, stage: chat.stage });
    }

    return entries;
  }, [processChat]);

  const isWorkspaceRoute = isWorkspacePath(location.pathname);
  const isAdminRoute = location.pathname === "/admin";
  const isUploadActive = processJob?.status === "queued" || processJob?.status === "running";
  const hasUploadEntries = processChat.length > 0;
  const showUploadErrorLogs = processJob?.status === "error" && hasUploadEntries;
  const showProcessOverlay = !processOverlayDismissed && (
    (mainView.view === "upload" && mainView.loading)
    || isUploadActive
    || showUploadErrorLogs
    || processOverlayDoneData !== null
  );
  const isOverlayStarting = mainView.view === "upload" && mainView.loading && !processJob;
  const showBackendOfflineBanner = backendOnline === false && !demoPreviewActive;
  const newLectureOverlayStyle = useMemo(() => {
    if (!newLectureButtonRect) return undefined;
    return {
      top: `${Math.max(12, Math.round(newLectureButtonRect.top))}px`,
      left: `${Math.round(newLectureButtonRect.right + 12)}px`,
    };
  }, [newLectureButtonRect]);
  const handleOpenLectureFromOverlay = useCallback((id: number) => {
    setProcessOverlayDismissed(true);
    setIsNewLectureOverlayOpen(false);
    navigate(`/lectures/${id}`);
  }, [navigate]);

  const handleViewLiveLecture = useCallback((id: number) => {
    setIsNewLectureOverlayOpen(false);
    navigate(`/lectures/${id}`);
  }, [navigate]);
  const canShowTrashAction = (
    isAdmin
    && isWorkspaceRoute
    && mainView.view === "results"
    && !demoPreviewActive
    && Boolean(mainView.lectureId ?? mainView.data.lecture_id)
  );
  const canToggleSaved = (
    mainView.view === "results"
    && !demoPreviewActive
    && Boolean(mainView.lectureId ?? mainView.data.lecture_id)
  );
  const canToggleArchive = canToggleSaved && isAdmin;
  const workspaceContent = (
    <WorkspaceRouteContent
      archiveBanner={archiveBanner}
      archivePending={archivePending}
      canShowTrashAction={canShowTrashAction}
      canToggleArchive={canToggleArchive}
      canToggleSaved={canToggleSaved}
      chatOpen={chatOpen}
      demoPreviewActive={demoPreviewActive}
      deletePending={deletePending}
      mainView={mainView}
      onAskAI={(text) => {
        setChatPrefill(text);
        setChatOpen(true);
      }}
      onCollapseChat={() => setChatOpen(false)}
      onExpandChat={() => setChatOpen(true)}
      onNewLecture={handleNewLecture}
      onNext={onNext}
      onOpenDeleteDialog={openDeleteDialog}
      onPrev={onPrev}
      onToggleArchive={() => void handleToggleArchive()}
      onToggleSaved={() => void handleToggleSaved()}
      prefillText={chatPrefill}
      regenBanner={regenBanner}
      regeneratingNotes={regeneratingNotes}
      regenerationProgressText={regenerationProgressText}
      saveBanner={saveBanner}
      savePending={savePending}
      showProcessOverlay={showProcessOverlay}
      sidebarCollapsed={sidebarCollapsed}
      toggleSidebar={toggleSidebar}
      viewState={activeSlideComputed}
    />
  );

  if (authState === "loading") {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", fontFamily: "system-ui, sans-serif" }}>
        Loading...
      </div>
    );
  }
  if (authState === "unauthenticated") {
    return (
      <div className="route-motion-shell route-motion-shell--auth" data-motion-phase={routeMotion.phase}>
        <div className="route-motion-content route-motion-content--auth">
          {authView === "login" ? (
            <LoginPage
              onLogin={handleLogin}
              onGoToSignup={() => setAuthView("signup")}
            />
          ) : (
            <SignupPage
              onSignup={handleLogin}
              onGoToLogin={() => setAuthView("login")}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <ErrorBoundary>
    <div className="app-shell">
      <Sidebar
        collapsed={sidebarCollapsed}
        savedLectures={sidebarSavedLectures}
        loading={lecturesLoading}
        selectedId={selectedId}
        onSelect={handleSelectLecture}
        onNewLecture={handleNewLecture}
        newLectureButtonRef={handleNewLectureButtonRef}
        isNewLectureOverlayOpen={isNewLectureOverlayOpen}
        onGoHome={handleGoHome}
        currentUserId={authUser?.uuid ?? ""}
        onOpenProfile={() => navigate("/profile")}
      />

      <main className={`main-content${isAdminRoute ? " main-content--admin" : ""}`}>
        {sidebarCollapsed && (
          <button
            className="sidebar-expand-btn"
            onClick={toggleSidebar}
            title="Expand sidebar"
            aria-label="Expand sidebar"
          >
            ›
          </button>
        )}
        <div className="route-motion-shell route-motion-shell--main" data-motion-phase={routeMotion.phase}>
          <div className="route-motion-content route-motion-content--main">
            {showBackendOfflineBanner && (
              <div className="banner error">Backend offline — start uvicorn on port 8000.</div>
            )}

            {isWorkspaceRoute && processBanner && (
              <div className={`banner ${processBanner.kind}`}>{processBanner.text}</div>
            )}

            <Routes location={routeMotion.displayLocation}>
              <Route
                path="/"
                element={(
                  <Homepage
                    savedLectures={savedLectures}
                    allLectures={lectures}
                    loading={lecturesLoading}
                    onOpenLecture={handleSelectLecture}
                  />
                )}
              />
              <Route
                path="/all-lectures"
                element={(
                  <div className="all-lectures-page app-surface">
                    <AllLecturesPlaceholder onGoHome={handleGoHome} />
                  </div>
                )}
              />
              <Route path="/workspace" element={<div className="workspace-page app-surface">{workspaceContent}</div>} />
              <Route path="/lectures/:lectureId" element={<div className="workspace-page app-surface">{workspaceContent}</div>} />
              <Route
                path="/admin"
                element={isAdmin ? <AdminPanel onBack={handleGoHome} /> : <Navigate to="/" replace />}
              />
              <Route
                path="/profile"
                element={(
                  <ProfilePage
                    authUser={authUser!}
                    profile={profile}
                    isAdmin={isAdmin}
                    archivedLectures={sidebarArchivedLectures}
                    onLogout={handleLogout}
                    onSelectLecture={handleSelectLecture}
                  />
                )}
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </div>
      </main>

      <NewLectureOverlay
        canRunDemo={isAdmin}
        consoleEntries={consoleEntries}
        loading={isUploadActive}
        onClose={closeNewLectureOverlay}
        onRunDemo={() => {
          setIsNewLectureOverlayOpen(false);
          void handleRunDemo();
        }}
        onSubmit={(pdf, recording, courseContext, lectureName) => {
          setIsNewLectureOverlayOpen(false);
          void handleSubmit(pdf, recording, courseContext, lectureName);
        }}
        open={isNewLectureOverlayOpen}
        progressPct={processJob?.progress_pct ?? null}
        style={newLectureOverlayStyle}
      />

      {showProcessOverlay && (
        <ProcessingConsoleOverlay
          job={processJob}
          consoleEntries={consoleEntries}
          statusLabel={uploadLoadingLabel}
          isStarting={isOverlayStarting}
          doneData={processOverlayDoneData}
          onDismiss={() => setProcessOverlayDismissed(true)}
          onOpenLecture={handleOpenLectureFromOverlay}
          onViewLiveLecture={handleViewLiveLecture}
        />
      )}


      {deleteDialogOpen && deleteTarget && (
        <div
          className="confirm-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-confirm-title"
          onClick={cancelDeleteDialog}
        >
          <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
            <h2 id="delete-confirm-title" className="confirm-title">Delete lecture?</h2>
            <p className="confirm-text">
              Delete <strong>"{deleteTarget.name}"</strong>? This permanently removes the lecture, PPTX, PDF, and stored notes.
            </p>
            <div className="confirm-actions">
              <button
                type="button"
                className="confirm-cancel-btn"
                onClick={cancelDeleteDialog}
                disabled={deletePending}
              >
                Cancel
              </button>
              <button
                type="button"
                className="confirm-delete-btn"
                onClick={() => void confirmDeleteDialog()}
                disabled={deletePending}
              >
                {deletePending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
    </ErrorBoundary>
  );
}
