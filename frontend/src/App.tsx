import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { Navigate, Route, Routes, useLocation, useMatch, useNavigate } from "react-router-dom";
import {
  ApiError,
  archiveLecture,
  buildAssetUrl,
  checkHealth,
  getLectures,
  getLecture,
  getProcessJob,
  getRegenerateNotesJob,
  startProcessJob,
  startRegenerateNotesJob,
  subscribeProcessJobEvents,
  subscribeRegenerateNotesEvents,
  findBestLectureWithNotesByName,
  unarchiveLecture,
} from "./api";
import UploadForm from "./components/UploadForm";
import SlideViewer from "./components/SlideViewer";
import TranscriptPanel from "./components/TranscriptPanel";
import Sidebar from "./components/Sidebar";
import ErrorBoundary from "./components/ErrorBoundary";
import { type ProcessChatEntry } from "./components/ProcessChat";
import Homepage from "./components/Homepage";
import AllLecturesPlaceholder from "./components/AllLecturesPlaceholder";
import {
  isEnrichedSlideInvalid,
  type ProcessResult,
  type LectureSummary,
  type RegenerateNotesJobStatus,
  type UploadLectureNamingInput,
  type UploadProcessJobEvent,
  type UploadProcessJobStatus,
} from "./types";

const REGENERATE_NOTES_AVAILABLE = (() => {
  const value = import.meta.env.VITE_ENABLE_REGENERATE_NOTES;
  if (typeof value !== "string") return false;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
})();
const ACTIVE_PROCESS_JOB_STORAGE_KEY = "lecture-summary.active-process-job-id";
const DEMO_MODE_STORAGE_KEY = "lectureSummary.demoMode";
const DEMO_LECTURE_QUERY = "F2VT26";
const DEMO_REGEN_STEP_MS = 650;
const DEMO_UPLOAD_STAGES: Array<{ label: string; stage: string; delayMs: number }> = [
  { label: "Validating files...", stage: "parse_slides", delayMs: 450 },
  { label: "Parsing PDF...", stage: "parse_slides", delayMs: 900 },
  { label: "Transcribing...", stage: "transcribe", delayMs: 1400 },
  { label: "Generating notes...", stage: "enrich", delayMs: 1100 },
];

type LectureData = ProcessResult & { name?: string; lecture_id?: number };

type MainView =
  | { view: "empty" }
  | { view: "upload"; loading: boolean; error?: string }
  | { view: "results"; data: LectureData; activeSlide: number; lectureId?: number };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function formatProcessStage(stage: string): string {
  return stage.replace(/_/g, " ");
}

export default function App() {
  const [mainView, setMainView] = useState<MainView>({ view: "empty" });
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [lectures, setLectures] = useState<LectureSummary[]>([]);
  const [lecturesLoading, setLecturesLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [processJob, setProcessJob] = useState<UploadProcessJobStatus | null>(null);
  const [processChat, setProcessChat] = useState<ProcessChatEntry[]>([]);
  const [regeneratingNotes, setRegeneratingNotes] = useState(false);
  const [regenBanner, setRegenBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [regenJob, setRegenJob] = useState<RegenerateNotesJobStatus | null>(null);
  const [archivePending, setArchivePending] = useState(false);
  const [archiveBanner, setArchiveBanner] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [uploadLoadingLabel, setUploadLoadingLabel] = useState("");
  const [processingLectureName, setProcessingLectureName] = useState<string | null>(null);
  const [demoSourceData, setDemoSourceData] = useState<(ProcessResult & { name: string; lecture_id: number }) | null>(null);
  const [demoMode, setDemoMode] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(DEMO_MODE_STORAGE_KEY) === "true";
  });

  const regenUnsubscribeRef = useRef<(() => void) | null>(null);
  const regenReconnectTimerRef = useRef<number | null>(null);
  const processUnsubscribeRef = useRef<(() => void) | null>(null);
  const processReconnectTimerRef = useRef<number | null>(null);
  const processLastEventIdRef = useRef(0);
  const demoRegenRunRef = useRef(0);
  const demoRunRef = useRef(0);
  const navigate = useNavigate();
  const location = useLocation();
  const lectureRouteMatch = useMatch("/lectures/:lectureId");
  const lectureRouteIdParam = lectureRouteMatch?.params.lectureId ?? null;

  const fetchLectures = useCallback(async () => {
    setLecturesLoading(true);
    try {
      const data = await getLectures();
      setLectures(data);
    } catch {
      // silently fail — sidebar shows empty
    } finally {
      setLecturesLoading(false);
    }
  }, []);

  useEffect(() => {
    checkHealth().then(setBackendOnline);
    fetchLectures();
  }, [fetchLectures]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(DEMO_MODE_STORAGE_KEY, demoMode ? "true" : "false");
  }, [demoMode]);

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

  const stopProcessSubscription = useCallback(() => {
    if (processUnsubscribeRef.current) {
      processUnsubscribeRef.current();
      processUnsubscribeRef.current = null;
    }
    if (processReconnectTimerRef.current !== null) {
      window.clearTimeout(processReconnectTimerRef.current);
      processReconnectTimerRef.current = null;
    }
  }, []);

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
    setArchiveBanner(null);
  }, [stopRegenerationSubscription]);

  const resetProcessUi = useCallback((clearPersisted = true) => {
    stopProcessSubscription();
    setProcessJob(null);
    setProcessChat([]);
    processLastEventIdRef.current = 0;
    setUploadLoadingLabel("");
    setProcessingLectureName(null);
    if (clearPersisted) {
      window.localStorage.removeItem(ACTIVE_PROCESS_JOB_STORAGE_KEY);
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

  const failProcessJob = useCallback((message: string, status?: UploadProcessJobStatus) => {
    stopProcessSubscription();
    window.localStorage.removeItem(ACTIVE_PROCESS_JOB_STORAGE_KEY);
    if (status) setProcessJob(status);
    setUploadLoadingLabel("");
    setMainView({ view: "upload", loading: false, error: message });
  }, [stopProcessSubscription]);

  const finishProcessJob = useCallback(async (status: UploadProcessJobStatus) => {
    stopProcessSubscription();
    window.localStorage.removeItem(ACTIVE_PROCESS_JOB_STORAGE_KEY);
    setProcessJob(status);

    const lectureId = status.lecture_id;
    if (!lectureId) {
      setMainView({ view: "upload", loading: false, error: "Processing completed but lecture id was missing." });
      return;
    }

    try {
      const data = await getLecture(lectureId);
      await fetchLectures();
      setSelectedId(lectureId);
      setMainView({ view: "results", data, activeSlide: 0, lectureId });
      setProcessChat([]);
      setUploadLoadingLabel("");
    } catch (err) {
      setMainView({
        view: "upload",
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }, [fetchLectures, stopProcessSubscription]);

  const subscribeToProcessJob = useCallback((jobId: string, lastEventId: number) => {
    stopProcessSubscription();
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
        void finishProcessJob(event);
      },
      onError: (event) => {
        setProcessJob(event);
        appendProcessChat(event, "error");
        setUploadLoadingLabel("");
        failProcessJob(event.error || "Upload processing failed.", event);
      },
      onTransportError: () => {
        stopProcessSubscription();
        void (async () => {
          try {
            const snapshot = await getProcessJob(jobId);
            setProcessJob(snapshot);
            if (snapshot.status === "done") {
              await finishProcessJob(snapshot);
              return;
            }
            if (snapshot.status === "error") {
              failProcessJob(snapshot.error || "Upload processing failed.", snapshot);
              return;
            }
            processReconnectTimerRef.current = window.setTimeout(() => {
              subscribeToProcessJob(jobId, processLastEventIdRef.current);
            }, 1000);
          } catch (err) {
            failProcessJob(err instanceof Error ? err.message : String(err));
          }
        })();
      },
    }, { lastEventId });
  }, [appendProcessChat, failProcessJob, finishProcessJob, stopProcessSubscription]);

  useEffect(() => {
    const storedJobId = window.localStorage.getItem(ACTIVE_PROCESS_JOB_STORAGE_KEY);
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
          await finishProcessJob(snapshot);
          return;
        }
        if (snapshot.status === "error") {
          failProcessJob(snapshot.error || "Upload processing failed.", snapshot);
          return;
        }
        subscribeToProcessJob(storedJobId, 0);
      } catch {
        window.localStorage.removeItem(ACTIVE_PROCESS_JOB_STORAGE_KEY);
        setUploadLoadingLabel("");
      }
    })();
  }, [failProcessJob, finishProcessJob, navigate, subscribeToProcessJob]);

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

    resetRegenerationUi();
    resetProcessUi(true);
    setSelectedId(null);
    setProcessingLectureName(`${DEMO_LECTURE_QUERY} - Demo (2026)`);
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

      const selectedDemo = await findBestLectureWithNotesByName(DEMO_LECTURE_QUERY);
      if (!selectedDemo) {
        setDemoSourceData(null);
        setMainView({
          view: "upload",
          loading: false,
          error: "No F2VT26 lecture with notes found. Open normal mode to process one.",
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
      };

      setDemoSourceData({
        ...selectedDemo.lecture,
        lecture_id: lectureId,
        name: lectureName,
      });

      setSelectedId(selectedDemo.summary.id);
      await fetchLectures();
      if (demoRunRef.current !== runId) return;
      setMainView({ view: "results", data: lectureData, activeSlide: 0, lectureId: selectedDemo.summary.id });
    } catch (err) {
      setDemoSourceData(null);
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

  const handleToggleDemo = useCallback(() => {
    demoRunRef.current += 1;
    setUploadLoadingLabel("");
    setDemoSourceData(null);
    setSelectedId(null);
    resetRegenerationUi();
    resetProcessUi(true);
    setMainView({ view: "upload", loading: false });
    setDemoMode((prev) => !prev);

    checkHealth().then(setBackendOnline);
    void fetchLectures();
  }, [fetchLectures, resetProcessUi, resetRegenerationUi]);

  async function handleSubmit(pdf: File, audio: File, naming: UploadLectureNamingInput) {
    if (demoMode) {
      await handleRunDemo();
      return;
    }

    resetRegenerationUi();
    resetProcessUi(true);
    setProcessChat([]);
    processLastEventIdRef.current = 0;
    setUploadLoadingLabel("");
    setProcessingLectureName(`${naming.courseid} - ${naming.lecture} (${naming.year})`);
    setMainView({ view: "upload", loading: true });
    try {
      const job = await startProcessJob(pdf, audio, naming);
      setSelectedId(null);
      setProcessJob(job);
      window.localStorage.setItem(ACTIVE_PROCESS_JOB_STORAGE_KEY, job.job_id);

      if (job.status === "done") {
        await finishProcessJob(job);
        return;
      }
      if (job.status === "error") {
        failProcessJob(job.error || "Upload processing failed.", job);
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
              await finishProcessJob(snapshot);
              return;
            }
            if (snapshot.status === "error") {
              failProcessJob(snapshot.error || "Upload processing failed.", snapshot);
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
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  const loadLectureIntoWorkspace = useCallback(async (id: number) => {
    resetRegenerationUi();
    resetProcessUi(false);
    setUploadLoadingLabel("");
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
    setSelectedId(id);
    if (location.pathname === `/lectures/${id}`) {
      void loadLectureIntoWorkspace(id);
      return;
    }
    navigate(`/lectures/${id}`);
  }, [loadLectureIntoWorkspace, location.pathname, navigate]);

  const handleNewLecture = useCallback(() => {
    resetRegenerationUi();
    if (!processJob || processJob.status === "done" || processJob.status === "error") {
      resetProcessUi(true);
    }
    setUploadLoadingLabel("");
    setArchiveBanner(null);
    setSelectedId(null);
    setMainView({ view: "upload", loading: false });
    navigate("/workspace");
  }, [navigate, processJob, resetProcessUi, resetRegenerationUi]);

  const handleGoHome = useCallback(() => {
    navigate("/");
  }, [navigate]);

  useEffect(() => {
    if (location.pathname === "/workspace" && mainView.view === "empty") {
      setMainView({ view: "upload", loading: false });
    }
  }, [location.pathname, mainView.view]);

  useEffect(() => {
    if (!lectureRouteIdParam) return;
    const parsedId = Number(lectureRouteIdParam);

    if (!Number.isInteger(parsedId) || parsedId <= 0) {
      resetRegenerationUi();
      resetProcessUi(false);
      setUploadLoadingLabel("");
      setArchiveBanner(null);
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
    if (mainView.view !== "results" || demoMode) return;

    const lectureId = mainView.lectureId ?? mainView.data.lecture_id;
    if (!lectureId) {
      setArchiveBanner({ kind: "error", text: "Cannot archive because lecture id is missing." });
      return;
    }

    const shouldArchive = !mainView.data.is_archived;
    setArchivePending(true);
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

    if (demoMode) {
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

  const isWorkspaceRoute = location.pathname === "/workspace" || location.pathname.startsWith("/lectures/");
  const isUploadActive = processJob?.status === "queued" || processJob?.status === "running";
  const hasUploadLabel = uploadLoadingLabel.trim().length > 0;
  const hasUploadEntries = processChat.length > 0;
  const showUploadErrorLogs = isWorkspaceRoute && processJob?.status === "error" && hasUploadEntries;
  const showSidebarUploadConsole = isUploadActive || hasUploadLabel || showUploadErrorLogs;
  const showBackendOfflineBanner = backendOnline === false && !(demoMode && demoSourceData);
  const workspaceContent = (
    <>
      {mainView.view === "empty" && (
        <div className="welcome-state">
          <div className="welcome-icon">📚</div>
          <h2 className="welcome-title">Welcome to LectureSummary</h2>
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
            demoMode={demoMode}
            onRunDemo={handleRunDemo}
            progressPct={processJob?.progress_pct ?? null}
            progressLabel={uploadLoadingLabel}
          />
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
                {demoMode && <span className="demo-pill">Demo Mode On</span>}
                {lectureId && REGENERATE_NOTES_AVAILABLE && (
                  <button
                    className="secondary"
                    onClick={handleRegenerateNotes}
                    disabled={regeneratingNotes || archivePending}
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
                {lectureId && !demoMode && (
                  <button
                    className="secondary"
                  onClick={handleToggleArchive}
                  disabled={archivePending || regeneratingNotes}
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
            {regeneratingNotes && (
              <div className="regen-progress">
                <span className="spinner spinner--dark-sm" />
                <span>{regenerationProgressText}</span>
              </div>
            )}
            {regenBanner && (
              <div className={`banner ${regenBanner.kind}`}>{regenBanner.text}</div>
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
        lectures={lectures}
        loading={lecturesLoading}
        selectedId={selectedId}
        onSelect={handleSelectLecture}
        onNewLecture={handleNewLecture}
        onGoHome={handleGoHome}
        demoMode={demoMode}
        onToggleDemo={handleToggleDemo}
        onRunDemo={handleRunDemo}
        showUploadConsole={showSidebarUploadConsole}
        uploadLoadingLabel={uploadLoadingLabel}
        processJob={processJob}
        processChat={processChat}
        processingLectureName={processingLectureName}
      />

      <main className="main-content">
        {showBackendOfflineBanner && (
          <div className="banner error">Backend offline — start uvicorn on port 8000.</div>
        )}

        {demoMode && (
          <div className="banner info">Demo Mode On — uses existing F2VT26 lecture data without API-key processing.</div>
        )}

        <Routes>
          <Route
            path="/"
            element={(
              <Homepage
                lectures={lectures}
                loading={lecturesLoading}
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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
    </ErrorBoundary>
  );
}
