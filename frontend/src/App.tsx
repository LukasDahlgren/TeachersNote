import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { Navigate, Route, Routes, useLocation, useMatch, useNavigate } from "react-router-dom";
import {
  ApiError,
  archiveLecture,
  buildAssetUrl,
  checkHealth,
  getCurrentUserId,
  getDeletedLectures,
  getLectures,
  getLecture,
  getMyLectures,
  getProfile,
  getProcessJob,
  getRegenerateNotesJob,
  registerAsAdmin,
  restoreLecture,
  saveLecture,
  startProcessJob,
  startRegenerateNotesJob,
  subscribeProcessJobEvents,
  subscribeRegenerateNotesEvents,
  findBestLectureWithNotesByExactName,
  trashLecture,
  unarchiveLecture,
  unsaveLecture,
} from "./api";
import UploadForm from "./components/UploadForm";
import SlideViewer from "./components/SlideViewer";
import TranscriptPanel from "./components/TranscriptPanel";
import Sidebar from "./components/Sidebar";
import ErrorBoundary from "./components/ErrorBoundary";
import ProcessChat, { type ProcessChatEntry } from "./components/ProcessChat";
import Homepage from "./components/Homepage";
import AllLecturesPlaceholder from "./components/AllLecturesPlaceholder";
import AdminPanel from "./components/AdminPanel";
import {
  isEnrichedSlideInvalid,
  type ProcessResult,
  type TeachersNoteSummary,
  type RegenerateNotesJobStatus,
  type UploadLectureNamingInput,
  type UploadRecordingInput,
  type UploadProcessJobEvent,
  type UploadProcessJobStatus,
  type StudentProfile,
} from "./types";

const REGENERATE_NOTES_AVAILABLE = (() => {
  const value = import.meta.env.VITE_ENABLE_REGENERATE_NOTES;
  if (typeof value !== "string") return false;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
})();
const ACTIVE_PROCESS_JOB_STORAGE_KEY = "teachers-note.active-process-job-id";
const LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY = "lecture-summary.active-process-job-id";
const IS_ADMIN_STORAGE_KEY = "teachers-note.is-admin";
const LEGACY_IS_ADMIN_STORAGE_KEY = "lecture-summary.is-admin";
const DEMO_LECTURE_NAME = "DB-lecture-12-2026";
const DEMO_REGEN_STEP_MS = 650;
const PROCESS_DETAIL_RETRY_DELAYS_MS = [700, 1300, 2000];
const PROCESS_STATUS_POLL_MS = 5000;
const DEMO_UPLOAD_STAGES: Array<{ label: string; stage: string; delayMs: number }> = [
  { label: "Validating files...", stage: "parse_slides", delayMs: 450 },
  { label: "Parsing PDF...", stage: "parse_slides", delayMs: 900 },
  { label: "Transcribing...", stage: "transcribe", delayMs: 1400 },
  { label: "Generating notes...", stage: "enrich", delayMs: 1100 },
];

type LectureData = ProcessResult & { name?: string; lecture_id?: number; is_saved?: boolean };

type MainView =
  | { view: "empty" }
  | { view: "upload"; loading: boolean; error?: string }
  | { view: "results"; data: LectureData; activeSlide: number; lectureId?: number };
type ProcessBanner = { kind: "success" | "error" | "info"; text: string };
type LectureRefreshResult = { ok: true } | { ok: false; error: string };

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

function readStorageWithMigration(primaryKey: string, legacyKey: string): string | null {
  const primary = window.localStorage.getItem(primaryKey)?.trim();
  if (primary) return primary;

  const legacy = window.localStorage.getItem(legacyKey)?.trim();
  if (!legacy) return null;

  window.localStorage.setItem(primaryKey, legacy);
  window.localStorage.removeItem(legacyKey);
  return legacy;
}

function clearStorageWithLegacy(primaryKey: string, legacyKey: string): void {
  window.localStorage.removeItem(primaryKey);
  window.localStorage.removeItem(legacyKey);
}

export default function App() {
  const [mainView, setMainView] = useState<MainView>({ view: "empty" });
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [lectures, setLectures] = useState<TeachersNoteSummary[]>([]);
  const [savedLectures, setSavedLectures] = useState<TeachersNoteSummary[]>([]);
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [deletedLectures, setDeletedLectures] = useState<TeachersNoteSummary[]>([]);
  const [lecturesLoading, setLecturesLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [processJob, setProcessJob] = useState<UploadProcessJobStatus | null>(null);
  const [processChat, setProcessChat] = useState<ProcessChatEntry[]>([]);
  const [processBanner, setProcessBanner] = useState<ProcessBanner | null>(null);
  const [lectureRefreshError, setLectureRefreshError] = useState<string | null>(null);
  const [regeneratingNotes, setRegeneratingNotes] = useState(false);
  const [regenBanner, setRegenBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [regenJob, setRegenJob] = useState<RegenerateNotesJobStatus | null>(null);
  const [savePending, setSavePending] = useState(false);
  const [saveBanner, setSaveBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [archivePending, setArchivePending] = useState(false);
  const [archiveBanner, setArchiveBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [uploadLoadingLabel, setUploadLoadingLabel] = useState("");
  const [processingLectureName, setProcessingLectureName] = useState<string | null>(null);
  const [demoPreviewActive, setDemoPreviewActive] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletePending, setDeletePending] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null);
  const [isAdmin, setIsAdmin] = useState(() =>
    readStorageWithMigration(IS_ADMIN_STORAGE_KEY, LEGACY_IS_ADMIN_STORAGE_KEY) === "true"
  );
  const [showAdminModal, setShowAdminModal] = useState(false);
  const [adminSecretInput, setAdminSecretInput] = useState("");
  const [adminRegisterError, setAdminRegisterError] = useState<string | null>(null);
  const [adminRegisterLoading, setAdminRegisterLoading] = useState(false);
  const currentUserId = getCurrentUserId();

  const regenUnsubscribeRef = useRef<(() => void) | null>(null);
  const regenReconnectTimerRef = useRef<number | null>(null);
  const processUnsubscribeRef = useRef<(() => void) | null>(null);
  const processReconnectTimerRef = useRef<number | null>(null);
  const processPollingTimerRef = useRef<number | null>(null);
  const processPollingInFlightRef = useRef(false);
  const processActiveJobIdRef = useRef<string | null>(null);
  const processTerminalHandledRef = useRef<Set<string>>(new Set());
  const processLastEventIdRef = useRef(0);
  const demoRegenRunRef = useRef(0);
  const demoRunRef = useRef(0);
  const navigate = useNavigate();
  const location = useLocation();
  const lectureRouteMatch = useMatch("/lectures/:lectureId");
  const lectureRouteIdParam = lectureRouteMatch?.params.lectureId ?? null;

  const fetchLectures = useCallback(async (): Promise<LectureRefreshResult> => {
    setLecturesLoading(true);
    try {
      const [catalog, saved] = await Promise.all([getLectures(), getMyLectures()]);
      let deleted: TeachersNoteSummary[] = [];
      if (isAdmin) {
        try {
          deleted = await getDeletedLectures();
        } catch (err) {
          console.warn("Failed to refresh deleted lectures list:", toErrorMessage(err));
        }
      }
      setLectures(catalog);
      setSavedLectures(saved);
      setDeletedLectures(deleted);
      setLectureRefreshError(null);
      return { ok: true };
    } catch (err) {
      const message = toErrorMessage(err);
      setLectureRefreshError(message);
      console.warn("Failed to refresh lectures list:", message);
      return { ok: false, error: message };
    } finally {
      setLecturesLoading(false);
    }
  }, [isAdmin]);

  const fetchProfile = useCallback(async () => {
    setProfileLoading(true);
    try {
      const nextProfile = await getProfile();
      setProfile(nextProfile);
    } catch (err) {
      console.warn("Failed to refresh profile:", toErrorMessage(err));
    } finally {
      setProfileLoading(false);
    }
  }, []);

  useEffect(() => {
    checkHealth().then(setBackendOnline);
    void fetchLectures();
    void fetchProfile();
  }, [fetchLectures, fetchProfile]);

  const stopRegenerationSubscription = useCallback(() => {
    if (regenUnsubscribeRef.current) {
      regenUnsubscribeRef.current();
      regenUnsubscribeRef.current = null;
    }
    if (regenReconnectTimerRef.current !== null) {
      window.clearTimeout(regenReconnectTimerRef.current);
      regenReconnectTimerRef.current = null;
    }
  }, []);

  const stopProcessPolling = useCallback(() => {
    if (processPollingTimerRef.current !== null) {
      window.clearInterval(processPollingTimerRef.current);
      processPollingTimerRef.current = null;
    }
    processPollingInFlightRef.current = false;
    processActiveJobIdRef.current = null;
  }, []);

  const stopProcessSubscription = useCallback(() => {
    if (processUnsubscribeRef.current) {
      processUnsubscribeRef.current();
      processUnsubscribeRef.current = null;
    }
    if (processReconnectTimerRef.current !== null) {
      window.clearTimeout(processReconnectTimerRef.current);
      processReconnectTimerRef.current = null;
    }
    stopProcessPolling();
  }, [stopProcessPolling]);

  useEffect(() => {
    return () => {
      stopRegenerationSubscription();
      stopProcessSubscription();
    };
  }, [stopProcessSubscription, stopRegenerationSubscription]);

  const resetRegenerationUi = useCallback(() => {
    stopRegenerationSubscription();
    demoRegenRunRef.current += 1;
    setRegeneratingNotes(false);
    setRegenBanner(null);
    setRegenJob(null);
    setSaveBanner(null);
    setArchiveBanner(null);
  }, [stopRegenerationSubscription]);

  const resetProcessUi = useCallback((clearPersisted = true) => {
    stopProcessSubscription();
    setProcessJob(null);
    setProcessChat([]);
    setProcessBanner(null);
    processLastEventIdRef.current = 0;
    setUploadLoadingLabel("");
    setProcessingLectureName(null);
    if (clearPersisted) {
      clearStorageWithLegacy(ACTIVE_PROCESS_JOB_STORAGE_KEY, LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY);
    }
  }, [stopProcessSubscription]);

  const appendProcessChat = useCallback((event: UploadProcessJobEvent, type: ProcessChatEntry["type"]) => {
    const eventId = typeof event.event_id === "number"
      ? event.event_id
      : processLastEventIdRef.current + 1;
    if (eventId <= processLastEventIdRef.current) return;

    processLastEventIdRef.current = eventId;
    const fallbackMessage = `${event.current_stage}: ${event.progress_pct}%`;
    const message = event.message?.trim() || fallbackMessage;

    setProcessChat((prev) => {
      const next = [
        ...prev,
        {
          eventId,
          type,
          message,
          stage: event.current_stage,
          progress: event.progress_pct,
          updatedAt: event.updated_at,
        },
      ];
      return next.slice(-400);
    });
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

  const failProcessJob = useCallback((message: string, status?: UploadProcessJobStatus) => {
    stopProcessSubscription();
    clearStorageWithLegacy(ACTIVE_PROCESS_JOB_STORAGE_KEY, LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY);
    if (status) setProcessJob(status);
    setUploadLoadingLabel("");
    setProcessBanner({ kind: "error", text: message });
    setMainView({ view: "upload", loading: false, error: message });
  }, [stopProcessSubscription]);

  const finishProcessJob = useCallback(async (status: UploadProcessJobStatus) => {
    stopProcessSubscription();
    clearStorageWithLegacy(ACTIVE_PROCESS_JOB_STORAGE_KEY, LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY);
    setProcessJob(status);

    const lectureId = status.lecture_id;
    if (!lectureId) {
      setMainView({ view: "upload", loading: false, error: "Processing completed but lecture id was missing." });
      return;
    }

    const refreshResult = await fetchLectures();
    let completionWarning: string | null = null;
    if (!refreshResult.ok) {
      completionWarning = `Lecture was saved, but refreshing Saved lectures failed (${refreshResult.error}).`;
    }

    try {
      const data = await fetchLectureWithRetry(lectureId);
      setSelectedId(lectureId);
      setMainView({ view: "results", data, activeSlide: 0, lectureId });
      setProcessBanner(completionWarning ? { kind: "error", text: completionWarning } : null);
      setProcessChat([]);
      setUploadLoadingLabel("");
    } catch (err) {
      const detailError = toErrorMessage(err);
      const refreshSuffix = refreshResult.ok
        ? ""
        : ` Also, refreshing Saved lectures failed (${refreshResult.error || lectureRefreshError || "unknown error"}).`;
      const message = (
        "Processing finished and lecture was saved, but we could not open it automatically. "
        + "Select it from Saved lectures and try again."
        + refreshSuffix
      );
      setProcessBanner({ kind: "info", text: message });
      setMainView({ view: "upload", loading: false, error: undefined });
      setProcessChat([]);
      setUploadLoadingLabel("");
      console.warn(`Failed to open lecture ${lectureId} after completion:`, detailError);
    }
  }, [fetchLectureWithRetry, fetchLectures, lectureRefreshError, stopProcessSubscription]);

  const handleProcessDoneOnce = useCallback(async (status: UploadProcessJobStatus) => {
    const jobId = status.job_id;
    if (processTerminalHandledRef.current.has(jobId)) {
      return;
    }
    processTerminalHandledRef.current.add(jobId);
    await finishProcessJob(status);
  }, [finishProcessJob]);

  const handleProcessErrorOnce = useCallback((message: string, status?: UploadProcessJobStatus) => {
    const jobId = status?.job_id;
    if (jobId) {
      if (processTerminalHandledRef.current.has(jobId)) {
        return;
      }
      processTerminalHandledRef.current.add(jobId);
    }
    failProcessJob(message, status);
  }, [failProcessJob]);

  const startProcessPolling = useCallback((jobId: string) => {
    processActiveJobIdRef.current = jobId;
    processPollingInFlightRef.current = false;

    if (processPollingTimerRef.current !== null) {
      window.clearInterval(processPollingTimerRef.current);
      processPollingTimerRef.current = null;
    }

    processPollingTimerRef.current = window.setInterval(() => {
      if (processPollingInFlightRef.current) return;
      if (processActiveJobIdRef.current !== jobId) return;

      processPollingInFlightRef.current = true;
      void (async () => {
        try {
          const snapshot = await getProcessJob(jobId);
          if (processActiveJobIdRef.current !== jobId) return;
          setProcessJob(snapshot);

          if (snapshot.status === "done") {
            await handleProcessDoneOnce(snapshot);
            return;
          }
          if (snapshot.status === "error") {
            handleProcessErrorOnce(snapshot.error || "Upload processing failed.", snapshot);
          }
        } catch (err) {
          console.warn("Process polling failed:", toErrorMessage(err));
        } finally {
          processPollingInFlightRef.current = false;
        }
      })();
    }, PROCESS_STATUS_POLL_MS);
  }, [handleProcessDoneOnce, handleProcessErrorOnce]);

  const subscribeToProcessJob = useCallback((jobId: string, lastEventId: number) => {
    stopProcessSubscription();
    processTerminalHandledRef.current.delete(jobId);
    startProcessPolling(jobId);

    processUnsubscribeRef.current = subscribeProcessJobEvents(jobId, {
      onProgress: (event) => {
        setProcessJob(event);
        appendProcessChat(event, "progress");
        setUploadLoadingLabel(`Processing: ${formatProcessStage(event.current_stage)} (${event.progress_pct}%)`);
        setMainView((prev) => (
          prev.view === "upload" ? { ...prev, loading: true, error: undefined } : prev
        ));
      },
      onLog: (event) => {
        setProcessJob(event);
        appendProcessChat(event, "log");
        setUploadLoadingLabel(`Processing: ${formatProcessStage(event.current_stage)} (${event.progress_pct}%)`);
      },
      onDone: (event) => {
        setProcessJob(event);
        appendProcessChat(event, "done");
        setUploadLoadingLabel("");
        void handleProcessDoneOnce(event);
      },
      onError: (event) => {
        setProcessJob(event);
        appendProcessChat(event, "error");
        setUploadLoadingLabel("");
        handleProcessErrorOnce(event.error || "Upload processing failed.", event);
      },
      onTransportError: () => {
        stopProcessSubscription();
        void (async () => {
          try {
            const snapshot = await getProcessJob(jobId);
            setProcessJob(snapshot);
            if (snapshot.status === "done") {
              await handleProcessDoneOnce(snapshot);
              return;
            }
            if (snapshot.status === "error") {
              handleProcessErrorOnce(snapshot.error || "Upload processing failed.", snapshot);
              return;
            }
            startProcessPolling(jobId);
            processReconnectTimerRef.current = window.setTimeout(() => {
              subscribeToProcessJob(jobId, processLastEventIdRef.current);
            }, 1000);
          } catch (err) {
            handleProcessErrorOnce(toErrorMessage(err));
          }
        })();
      },
    }, { lastEventId });
  }, [
    appendProcessChat,
    handleProcessDoneOnce,
    handleProcessErrorOnce,
    startProcessPolling,
    stopProcessSubscription,
  ]);

  useEffect(() => {
    const storedJobId = readStorageWithMigration(
      ACTIVE_PROCESS_JOB_STORAGE_KEY,
      LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY,
    );
    if (!storedJobId) return;
    const initialPath = window.location.pathname;
    if (initialPath !== "/workspace" && !initialPath.startsWith("/lectures/")) {
      navigate("/workspace", { replace: true });
    }

    setMainView({ view: "upload", loading: true });
    setProcessChat([]);
    processLastEventIdRef.current = 0;

    void (async () => {
      try {
        const snapshot = await getProcessJob(storedJobId);
        setProcessJob(snapshot);
        setUploadLoadingLabel(`Processing: ${formatProcessStage(snapshot.current_stage)} (${snapshot.progress_pct}%)`);
        if (snapshot.status === "done") {
          await handleProcessDoneOnce(snapshot);
          return;
        }
        if (snapshot.status === "error") {
          handleProcessErrorOnce(snapshot.error || "Upload processing failed.", snapshot);
          return;
        }
        subscribeToProcessJob(storedJobId, 0);
      } catch {
        clearStorageWithLegacy(ACTIVE_PROCESS_JOB_STORAGE_KEY, LEGACY_ACTIVE_PROCESS_JOB_STORAGE_KEY);
        setUploadLoadingLabel("");
      }
    })();
  }, [handleProcessDoneOnce, handleProcessErrorOnce, navigate, subscribeToProcessJob]);

  const finishRegeneration = useCallback(async (lectureId: number, status: RegenerateNotesJobStatus) => {
    stopRegenerationSubscription();
    setRegenJob(status);
    try {
      const data = await getLecture(lectureId);
      setMainView((prev) => (
        prev.view === "results"
          ? { ...prev, data, lectureId }
          : prev
      ));
      setRegenBanner({
        kind: "success",
        text: status.regenerated_slides === 0
          ? "All slide notes are already valid."
          : `Regenerated notes for ${status.regenerated_slides} slide${status.regenerated_slides === 1 ? "" : "s"}.`,
      });
    } catch (err) {
      setRegenBanner({
        kind: "error",
        text: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRegeneratingNotes(false);
    }
  }, [stopRegenerationSubscription]);

  const failRegeneration = useCallback((message: string, status?: RegenerateNotesJobStatus) => {
    stopRegenerationSubscription();
    if (status) setRegenJob(status);
    setRegeneratingNotes(false);
    setRegenBanner({ kind: "error", text: message });
  }, [stopRegenerationSubscription]);

  const subscribeToRegenerationJob = useCallback((jobId: string, lectureId: number) => {
    stopRegenerationSubscription();

    regenUnsubscribeRef.current = subscribeRegenerateNotesEvents(jobId, {
      onProgress: (event) => {
        setRegenJob(event);
      },
      onDone: (event) => {
        void finishRegeneration(lectureId, event);
      },
      onError: (event) => {
        failRegeneration(event.error || "Regeneration failed.", event);
      },
      onTransportError: () => {
        stopRegenerationSubscription();
        void (async () => {
          try {
            const snapshot = await getRegenerateNotesJob(jobId);
            setRegenJob(snapshot);
            if (snapshot.status === "done") {
              await finishRegeneration(lectureId, snapshot);
              return;
            }
            if (snapshot.status === "error") {
              failRegeneration(snapshot.error || "Regeneration failed.", snapshot);
              return;
            }
            regenReconnectTimerRef.current = window.setTimeout(() => {
              subscribeToRegenerationJob(jobId, lectureId);
            }, 1000);
          } catch (err) {
            failRegeneration(
              err instanceof Error ? err.message : String(err),
            );
          }
        })();
      },
    });
  }, [failRegeneration, finishRegeneration, stopRegenerationSubscription]);

  const handleRunDemo = useCallback(async () => {
    const runId = demoRunRef.current + 1;
    demoRunRef.current = runId;

    setDemoPreviewActive(true);
    resetRegenerationUi();
    resetProcessUi(true);
    setProcessBanner(null);
    setSelectedId(null);
    setProcessingLectureName(`${DEMO_LECTURE_NAME} - Demo (2026)`);
    setMainView({ view: "upload", loading: true });

    try {
      // Simulate progress through stages with increasing percentages
      const stageProgressMap: Record<string, { start: number; end: number }> = {
        "Validating files...": { start: 0, end: 10 },
        "Parsing PDF...": { start: 10, end: 35 },
        "Transcribing...": { start: 35, end: 75 },
        "Generating notes...": { start: 75, end: 100 },
      };

      for (const stage of DEMO_UPLOAD_STAGES) {
        if (demoRunRef.current !== runId) return;

        const progressRange = stageProgressMap[stage.label];
        const startProgress = progressRange?.start ?? 0;
        const endProgress = progressRange?.end ?? 100;
        const stepSize = (endProgress - startProgress) / Math.max(1, Math.ceil(stage.delayMs / 100));

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
  }, [fetchLectures, resetProcessUi, resetRegenerationUi]);

  async function handleSubmit(pdf: File, recording: UploadRecordingInput, naming: UploadLectureNamingInput) {
    demoRunRef.current += 1;
    setDemoPreviewActive(false);
    resetRegenerationUi();
    resetProcessUi(true);
    setProcessChat([]);
    processLastEventIdRef.current = 0;
    setProcessBanner(null);
    setUploadLoadingLabel("");
    setProcessingLectureName(`${naming.courseid} - ${naming.lecture} (${naming.year})`);
    setMainView({ view: "upload", loading: true });
    try {
      const job = await startProcessJob(pdf, recording, naming);
      processTerminalHandledRef.current.delete(job.job_id);
      setSelectedId(null);
      setProcessJob(job);
      window.localStorage.setItem(ACTIVE_PROCESS_JOB_STORAGE_KEY, job.job_id);

      if (job.status === "done") {
        await handleProcessDoneOnce(job);
        return;
      }
      if (job.status === "error") {
        handleProcessErrorOnce(job.error || "Upload processing failed.", job);
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
            processLastEventIdRef.current = 0;
            window.localStorage.setItem(ACTIVE_PROCESS_JOB_STORAGE_KEY, activeJobId);

            if (snapshot.status === "done") {
              await handleProcessDoneOnce(snapshot);
              return;
            }
            if (snapshot.status === "error") {
              handleProcessErrorOnce(snapshot.error || "Upload processing failed.", snapshot);
              return;
            }
            subscribeToProcessJob(activeJobId, 0);
            return;
          } catch (snapshotErr) {
            setMainView({
              view: "upload",
              loading: false,
              error: snapshotErr instanceof Error ? snapshotErr.message : String(snapshotErr),
            });
            return;
          }
        }
      }

      setMainView({
        view: "upload",
        loading: false,
        error: toErrorMessage(err),
      });
    }
  }

  const loadLectureIntoWorkspace = useCallback(async (id: number) => {
    demoRunRef.current += 1;
    setDemoPreviewActive(false);
    resetRegenerationUi();
    resetProcessUi(false);
    setProcessBanner(null);
    setUploadLoadingLabel("");
    setSaveBanner(null);
    setArchiveBanner(null);
    setSelectedId(id);
    setMainView({ view: "upload", loading: true });
    try {
      const data = await getLecture(id);
      setMainView({ view: "results", data, activeSlide: 0, lectureId: id });
    } catch (err) {
      setMainView({ view: "upload", loading: false, error: String(err) });
    }
  }, [resetProcessUi, resetRegenerationUi]);

  const handleSelectLecture = useCallback((id: number) => {
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
    resetRegenerationUi();
    if (!processJob || processJob.status === "done" || processJob.status === "error") {
      resetProcessUi(true);
    }
    setProcessBanner(null);
    setUploadLoadingLabel("");
    setSaveBanner(null);
    setArchiveBanner(null);
    setSelectedId(null);
    setMainView({ view: "upload", loading: false });
    navigate("/workspace");
  }, [navigate, processJob, resetProcessUi, resetRegenerationUi]);

  const handleGoHome = useCallback(() => {
    demoRunRef.current += 1;
    setDemoPreviewActive(false);
    navigate("/");
  }, [navigate]);

  const handleOpenAdminPanel = useCallback(() => {
    navigate("/admin");
  }, [navigate]);

  const handleLogout = useCallback(() => {
    clearStorageWithLegacy(IS_ADMIN_STORAGE_KEY, LEGACY_IS_ADMIN_STORAGE_KEY);
    setIsAdmin(false);
    navigate("/");
  }, [navigate]);

  const handleRegisterAdmin = useCallback(async () => {
    setAdminRegisterError(null);
    setAdminRegisterLoading(true);
    try {
      await registerAsAdmin(adminSecretInput.trim());
      window.localStorage.setItem(IS_ADMIN_STORAGE_KEY, "true");
      setIsAdmin(true);
      setShowAdminModal(false);
      setAdminSecretInput("");
    } catch (err) {
      setAdminRegisterError(err instanceof ApiError ? err.message : "Registration failed.");
    } finally {
      setAdminRegisterLoading(false);
    }
  }, [adminSecretInput]);

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
      setUploadLoadingLabel("");
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

    setDeleteTarget({
      id: lectureId,
      name: mainView.data.name?.trim() || "this lecture",
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

  async function handleRestoreLecture(id: number) {
    try {
      await restoreLecture(id);
      await fetchLectures();
    } catch (err) {
      console.warn("Failed to restore lecture:", err);
    }
  }

  const handleProfileChange = useCallback((nextProfile: StudentProfile) => {
    setProfile(nextProfile);
  }, []);

  async function handleRegenerateNotes() {
    if (mainView.view !== "results") return;
    if (!REGENERATE_NOTES_AVAILABLE) {
      setRegenBanner({ kind: "error", text: "Regenerate notes is currently unavailable." });
      return;
    }
    const lectureId = mainView.lectureId ?? mainView.data.lecture_id;
    if (!lectureId) {
      setRegenBanner({ kind: "error", text: "Cannot regenerate notes because lecture id is missing." });
      return;
    }

    if (demoPreviewActive) {
      const runId = demoRegenRunRef.current + 1;
      demoRegenRunRef.current = runId;

      stopRegenerationSubscription();
      setRegeneratingNotes(true);
      setRegenBanner(null);

      const totalSlides = mainView.data.slides.length;
      const invalidSlides = mainView.data.enhanced.filter((slide) => isEnrichedSlideInvalid(slide)).length;
      const jobId = `demo-${Date.now()}`;
      const buildDemoStatus = (overrides: Partial<RegenerateNotesJobStatus> = {}): RegenerateNotesJobStatus => ({
        job_id: jobId,
        lecture_id: lectureId,
        status: "running",
        total_slides: totalSlides,
        completed_slides: 0,
        current_slide: null,
        regenerated_slides: 0,
        error: null,
        updated_at: new Date().toISOString(),
        ...overrides,
      });

      setRegenJob(buildDemoStatus());

      for (let idx = 0; idx < totalSlides; idx += 1) {
        await sleep(DEMO_REGEN_STEP_MS);
        if (demoRegenRunRef.current !== runId) return;

        const currentSlideNumber = mainView.data.slides[idx]?.slide ?? (idx + 1);
        setRegenJob(buildDemoStatus({
          completed_slides: idx + 1,
          current_slide: currentSlideNumber,
          regenerated_slides: invalidSlides,
        }));
      }

      if (demoRegenRunRef.current !== runId) return;

      setRegenJob(buildDemoStatus({
        status: "done",
        completed_slides: totalSlides,
        current_slide: null,
        regenerated_slides: invalidSlides,
      }));
      setRegeneratingNotes(false);
      setRegenBanner({
        kind: "success",
        text: invalidSlides === 0
          ? "All slide notes are already valid."
          : `Regeneration simulation complete for ${invalidSlides} slide${invalidSlides === 1 ? "" : "s"}.`,
      });
      return;
    }

    stopRegenerationSubscription();
    setRegeneratingNotes(true);
    setRegenBanner(null);
    setSaveBanner(null);
    setArchiveBanner(null);
    try {
      const job = await startRegenerateNotesJob(lectureId);
      setRegenJob(job);

      if (job.status === "done") {
        await finishRegeneration(lectureId, job);
        return;
      }
      if (job.status === "error") {
        failRegeneration(job.error || "Regeneration failed.", job);
        return;
      }
      subscribeToRegenerationJob(job.job_id, lectureId);
    } catch (err) {
      failRegeneration(err instanceof Error ? err.message : String(err));
    }
  }

  const activeSlideComputed = useMemo(() => {
    if (mainView.view !== "results") return null;
    const { data, activeSlide } = mainView;
    const alignment = data.alignment.find(a => a.slide === activeSlide + 1);
    const segments = alignment
      ? data.transcript.slice(alignment.start_segment, alignment.end_segment + 1)
      : [];
    return { data, activeSlide, segments };
  }, [mainView]);

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

  const isWorkspaceRoute = location.pathname === "/workspace" || location.pathname.startsWith("/lectures/");
  const isUploadActive = processJob?.status === "queued" || processJob?.status === "running";
  const hasUploadLabel = uploadLoadingLabel.trim().length > 0;
  const hasUploadEntries = processChat.length > 0;
  const showUploadErrorLogs = isWorkspaceRoute && processJob?.status === "error" && hasUploadEntries;
  const showSidebarUploadConsole = isUploadActive || hasUploadLabel || showUploadErrorLogs;
  const showBackendOfflineBanner = backendOnline === false && !demoPreviewActive;
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
    <>
      {mainView.view === "empty" && (
        <div className="welcome-state">
          <div className="welcome-icon">📚</div>
          <h2 className="welcome-title">Welcome to TeachersNote</h2>
          <p className="welcome-sub">
            Select a lecture from the sidebar or click{" "}
            <button className="welcome-link-btn" onClick={handleNewLecture}>
              + New Lecture
            </button>{" "}
            to get started.
          </p>
        </div>
      )}

      {mainView.view === "upload" && (
        <>
          <UploadForm
            onSubmit={handleSubmit}
            loading={mainView.loading}
            onRunDemo={handleRunDemo}
            progressPct={processJob?.progress_pct ?? null}
            progressLabel={uploadLoadingLabel}
          />
          {mainView.loading && processJob && (
            <ProcessChat
              entries={processChat}
              job={processJob}
              lectureName={processingLectureName}
            />
          )}
          {mainView.error && (
            <div className="banner error">{mainView.error}</div>
          )}
        </>
      )}

      {mainView.view === "results" && activeSlideComputed && (() => {
        const { data, activeSlide, segments } = activeSlideComputed;
        const lectureId = mainView.lectureId ?? data.lecture_id;
        const downloadHref = buildAssetUrl(data.download_url);
        const pdfUrl = buildAssetUrl(data.pdf_url);

        return (
          <div className="results">
              <div className="results-header">
                <span className="results-lecture-name">{data.name ?? "Lecture"}</span>
                {demoPreviewActive && <span className="demo-pill">Demo preview</span>}
                <div className="results-actions">
                  {lectureId && REGENERATE_NOTES_AVAILABLE && (
                    <button
                      className="secondary"
                      onClick={handleRegenerateNotes}
                      disabled={regeneratingNotes || archivePending || savePending}
                    >
                      {regeneratingNotes ? "Regenerating..." : "Regenerate notes"}
                    </button>
                  )}
                  {lectureId && !REGENERATE_NOTES_AVAILABLE && (
                    <button
                      className="secondary"
                      disabled
                    >
                      Regenerate unavailable
                    </button>
                  )}
                  {canToggleSaved && (
                    <button
                      className="secondary"
                      onClick={handleToggleSaved}
                      disabled={savePending || archivePending || regeneratingNotes}
                    >
                      {savePending
                        ? (data.is_saved ? "Removing..." : "Saving...")
                        : (data.is_saved ? "Remove from Saved" : "Save")}
                    </button>
                  )}
                  {canToggleArchive && (
                    <button
                      className="secondary"
                      onClick={handleToggleArchive}
                      disabled={archivePending || savePending || regeneratingNotes}
                    >
                      {archivePending
                        ? (data.is_archived ? "Unarchiving..." : "Archiving...")
                        : (data.is_archived ? "Unarchive" : "Archive")}
                    </button>
                  )}
                  {downloadHref && (
                    <a href={downloadHref} download>
                      <button>Download PPTX</button>
                    </a>
                  )}
                </div>
            </div>
            {regeneratingNotes && (
              <div className="regen-progress">
                <span className="spinner spinner--dark-sm" />
                <span>{regenerationProgressText}</span>
              </div>
            )}
            {regenBanner && (
              <div className={`banner ${regenBanner.kind}`}>{regenBanner.text}</div>
            )}
            {saveBanner && (
              <div className={`banner ${saveBanner.kind}`}>{saveBanner.text}</div>
            )}
            {archiveBanner && (
              <div className={`banner ${archiveBanner.kind}`}>{archiveBanner.text}</div>
            )}
            <div className="results-body">
              <SlideViewer
                slideText={data.slides[activeSlide]?.text ?? ""}
                slideNumber={activeSlide + 1}
                total={data.slides.length}
                onPrev={onPrev}
                onNext={onNext}
                pdfUrl={pdfUrl}
              />
              <TranscriptPanel
                segments={segments}
                enriched={data.enhanced?.find(e => e.slide === activeSlide + 1)}
              />
            </div>
          </div>
        );
      })()}
    </>
  );

  return (
    <ErrorBoundary>
    <div className="app-shell">
      <Sidebar
        savedLectures={sidebarSavedLectures}
        archivedLectures={sidebarArchivedLectures}
        deletedLectures={deletedLectures}
        loading={lecturesLoading}
        selectedId={selectedId}
        onSelect={handleSelectLecture}
        onNewLecture={handleNewLecture}
        onGoHome={handleGoHome}
        onRestore={handleRestoreLecture}
        showUploadConsole={showSidebarUploadConsole}
        uploadLoadingLabel={uploadLoadingLabel}
        processJob={processJob}
        processChat={processChat}
        processingLectureName={processingLectureName}
        isAdmin={isAdmin}
        currentUserId={currentUserId}
        onOpenAdminPanel={handleOpenAdminPanel}
        onRegisterAdmin={() => setShowAdminModal(true)}
        onLogout={handleLogout}
      />

      <main className="main-content">
        {showBackendOfflineBanner && (
          <div className="banner error">Backend offline — start uvicorn on port 8000.</div>
        )}

        {isWorkspaceRoute && processBanner && (
          <div className={`banner ${processBanner.kind}`}>{processBanner.text}</div>
        )}

        {canShowTrashAction && (
          <button
            type="button"
            className="trash-fab"
            onClick={openDeleteDialog}
            disabled={archivePending || savePending || regeneratingNotes || deletePending}
            aria-label="Delete lecture"
            title="Delete lecture"
          >
            <svg className="trash-fab-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M3 6h18M8 6V4h8v2m-9 0l1 14h8l1-14M10 10v7m4-7v7"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}

        <Routes>
          <Route
            path="/"
            element={(
              <Homepage
                savedLectures={savedLectures}
                allLectures={lectures}
                loading={lecturesLoading}
                profile={profile}
                profileLoading={profileLoading}
                onProfileChange={handleProfileChange}
                onOpenLecture={handleSelectLecture}
              />
            )}
          />
          <Route
            path="/all-lectures"
            element={<AllLecturesPlaceholder onGoHome={handleGoHome} />}
          />
          <Route path="/workspace" element={workspaceContent} />
          <Route path="/lectures/:lectureId" element={workspaceContent} />
          <Route
            path="/admin"
            element={isAdmin ? <AdminPanel onBack={handleGoHome} /> : <Navigate to="/" replace />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

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
              Delete <strong>"{deleteTarget.name}"</strong>? This will move the PPTX to Recently Deleted.
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

      {showAdminModal && (
        <div className="modal-overlay" onClick={() => setShowAdminModal(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h2 className="modal-title">Register as Admin</h2>
            <p className="modal-description">Enter the admin secret to gain admin access.</p>
            <input
              className="modal-input"
              type="password"
              placeholder="Admin secret"
              value={adminSecretInput}
              onChange={(e) => setAdminSecretInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleRegisterAdmin(); }}
              autoFocus
            />
            {adminRegisterError && (
              <p className="modal-error">{adminRegisterError}</p>
            )}
            <div className="modal-actions">
              <button
                className="modal-btn modal-btn--secondary"
                onClick={() => { setShowAdminModal(false); setAdminSecretInput(""); setAdminRegisterError(null); }}
              >
                Cancel
              </button>
              <button
                className="modal-btn modal-btn--primary"
                onClick={() => void handleRegisterAdmin()}
                disabled={adminRegisterLoading || !adminSecretInput.trim()}
              >
                {adminRegisterLoading ? "Registering…" : "Register"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </ErrorBoundary>
  );
}
