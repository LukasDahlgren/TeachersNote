import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, getProcessJob, subscribeProcessJobEvents } from "../api";
import type { EnrichedSlide, UploadProcessJobEvent, UploadProcessJobStatus } from "../types";

export interface ProcessChatEntry {
  eventId: number;
  type: "log" | "done" | "error";
  message: string;
  stage: string;
  progress: number;
  updatedAt: string;
}

interface ProcessJobControllerOptions {
  activeProcessJobStorageKey?: string;
  getProcessJobSnapshot?: typeof getProcessJob;
  legacyActiveProcessJobStorageKey?: string;
  onDone?: (status: UploadProcessJobStatus) => void | Promise<void>;
  onError?: (message: string, status?: UploadProcessJobStatus) => void;
  onLectureAdded?: (lectureId: number) => void;
  pollMs?: number;
  subscribeToProcessJobEvents?: typeof subscribeProcessJobEvents;
}

function readStorageWithMigration(primaryKey: string, legacyKey: string): string | null {
  if (typeof window === "undefined") return null;

  const primary = window.localStorage.getItem(primaryKey)?.trim();
  if (primary) return primary;

  const legacy = window.localStorage.getItem(legacyKey)?.trim();
  if (!legacy) return null;

  window.localStorage.setItem(primaryKey, legacy);
  window.localStorage.removeItem(legacyKey);
  return legacy;
}

function clearStorageWithLegacy(primaryKey: string, legacyKey: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(primaryKey);
  window.localStorage.removeItem(legacyKey);
}

function formatProcessStage(stage: string): string {
  return stage.replace(/_/g, " ");
}

export function useProcessJobController({
  activeProcessJobStorageKey = "teachers-note.active-process-job-id",
  getProcessJobSnapshot = getProcessJob,
  legacyActiveProcessJobStorageKey = "lecture-summary.active-process-job-id",
  onDone,
  onError,
  onLectureAdded,
  pollMs = 5000,
  subscribeToProcessJobEvents = subscribeProcessJobEvents,
}: ProcessJobControllerOptions = {}) {
  const [job, setJob] = useState<UploadProcessJobStatus | null>(null);
  const [uploadLoadingLabel, setUploadLoadingLabel] = useState("");
  const [processChat, setProcessChat] = useState<ProcessChatEntry[]>([]);
  const [liveEnrichedSlides, setLiveEnrichedSlides] = useState<EnrichedSlide[]>([]);

  const unsubscribeRef = useRef<(() => void) | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const pollingTimerRef = useRef<number | null>(null);
  const pollingInFlightRef = useRef(false);
  const activeJobIdRef = useRef<string | null>(null);
  const terminalHandledRef = useRef<Set<string>>(new Set());
  const lastEventIdRef = useRef(0);
  const lectureAddedRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollingTimerRef.current !== null) {
      window.clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
    pollingInFlightRef.current = false;
    activeJobIdRef.current = null;
  }, []);

  const stop = useCallback(() => {
    if (unsubscribeRef.current) {
      unsubscribeRef.current();
      unsubscribeRef.current = null;
    }
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    stopPolling();
  }, [stopPolling]);

  useEffect(() => stop, [stop]);

  const clearPersistedJobId = useCallback(() => {
    clearStorageWithLegacy(activeProcessJobStorageKey, legacyActiveProcessJobStorageKey);
  }, [activeProcessJobStorageKey, legacyActiveProcessJobStorageKey]);

  const persistJobId = useCallback((jobId: string) => {
    window.localStorage.setItem(activeProcessJobStorageKey, jobId);
  }, [activeProcessJobStorageKey]);

  const reset = useCallback((clearPersisted = true) => {
    stop();
    setJob(null);
    setProcessChat([]);
    setLiveEnrichedSlides([]);
    setUploadLoadingLabel("");
    lastEventIdRef.current = 0;
    lectureAddedRef.current = false;
    if (clearPersisted) {
      clearPersistedJobId();
    }
  }, [clearPersistedJobId, stop]);

  const appendProcessChat = useCallback((event: UploadProcessJobEvent, type: ProcessChatEntry["type"]) => {
    const eventId = typeof event.event_id === "number"
      ? event.event_id
      : lastEventIdRef.current + 1;
    if (eventId <= lastEventIdRef.current) return;

    lastEventIdRef.current = eventId;
    const fallbackMessage = `${event.current_stage}: ${event.progress_pct}%`;
    const message = event.message?.trim() || fallbackMessage;

    setProcessChat((previous) => {
      const next = [
        ...previous,
        {
          eventId,
          message,
          progress: event.progress_pct,
          stage: event.current_stage,
          type,
          updatedAt: event.updated_at,
        },
      ];
      return next.slice(-400);
    });
  }, []);

  const handleDoneOnce = useCallback(async (status: UploadProcessJobStatus) => {
    if (terminalHandledRef.current.has(status.job_id)) return;
    terminalHandledRef.current.add(status.job_id);
    stop();
    clearPersistedJobId();
    await onDone?.(status);
  }, [clearPersistedJobId, onDone, stop]);

  const handleErrorOnce = useCallback((message: string, status?: UploadProcessJobStatus) => {
    const jobId = status?.job_id;
    if (jobId) {
      if (terminalHandledRef.current.has(jobId)) return;
      terminalHandledRef.current.add(jobId);
    }
    stop();
    clearPersistedJobId();
    onError?.(message, status);
  }, [clearPersistedJobId, onError, stop]);

  const startPolling = useCallback((jobId: string) => {
    activeJobIdRef.current = jobId;
    pollingInFlightRef.current = false;

    if (pollingTimerRef.current !== null) {
      window.clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }

    pollingTimerRef.current = window.setInterval(() => {
      if (pollingInFlightRef.current) return;
      if (activeJobIdRef.current !== jobId) return;

      pollingInFlightRef.current = true;
      void (async () => {
        try {
          const snapshot = await getProcessJobSnapshot(jobId);
          if (activeJobIdRef.current !== jobId) return;
          setJob(snapshot);

          if (snapshot.status === "done") {
            await handleDoneOnce(snapshot);
            return;
          }
          if (snapshot.status === "error") {
            handleErrorOnce(snapshot.error || "Upload processing failed.", snapshot);
          }
        } finally {
          pollingInFlightRef.current = false;
        }
      })();
    }, pollMs);
  }, [getProcessJobSnapshot, handleDoneOnce, handleErrorOnce, pollMs]);

  const attachToJob = useCallback((jobId: string, lastEventId = 0) => {
    stop();
    terminalHandledRef.current.delete(jobId);
    startPolling(jobId);

    unsubscribeRef.current = subscribeToProcessJobEvents(jobId, {
      onProgress: (event) => {
        setJob(event);
        setUploadLoadingLabel(`Processing: ${formatProcessStage(event.current_stage)} (${event.progress_pct}%)`);
        if (event.lecture_id && !lectureAddedRef.current) {
          lectureAddedRef.current = true;
          onLectureAdded?.(event.lecture_id);
        }
      },
      onLog: (event) => {
        setJob(event);
        appendProcessChat(event, "log");
        setUploadLoadingLabel(`Processing: ${formatProcessStage(event.current_stage)} (${event.progress_pct}%)`);
      },
      onSlideEnriched: (event) => {
        setLiveEnrichedSlides((previous) => {
          const filtered = previous.filter((slide) => slide.slide !== event.slide);
          return [...filtered, event];
        });
      },
      onDone: (event) => {
        setJob(event);
        appendProcessChat(event, "done");
        setUploadLoadingLabel("");
        void handleDoneOnce(event);
      },
      onError: (event) => {
        setJob(event);
        appendProcessChat(event, "error");
        setUploadLoadingLabel("");
        handleErrorOnce(event.error || "Upload processing failed.", event);
      },
      onTransportError: () => {
        stop();
        void (async () => {
          try {
            const snapshot = await getProcessJobSnapshot(jobId);
            setJob(snapshot);
            if (snapshot.status === "done") {
              await handleDoneOnce(snapshot);
              return;
            }
            if (snapshot.status === "error") {
              handleErrorOnce(snapshot.error || "Upload processing failed.", snapshot);
              return;
            }
            startPolling(jobId);
            reconnectTimerRef.current = window.setTimeout(() => {
              attachToJob(jobId, lastEventIdRef.current);
            }, 1000);
          } catch (error) {
            handleErrorOnce(error instanceof Error ? error.message : String(error));
          }
        })();
      },
    }, { lastEventId });
  }, [
    appendProcessChat,
    getProcessJobSnapshot,
    handleDoneOnce,
    handleErrorOnce,
    onLectureAdded,
    startPolling,
    stop,
    subscribeToProcessJobEvents,
  ]);

  const resumePersistedJob = useCallback(async (): Promise<string | null> => {
    const storedJobId = readStorageWithMigration(
      activeProcessJobStorageKey,
      legacyActiveProcessJobStorageKey,
    );
    if (!storedJobId) return null;

    setProcessChat([]);
    lastEventIdRef.current = 0;

    try {
      const snapshot = await getProcessJobSnapshot(storedJobId);
      setJob(snapshot);
      setUploadLoadingLabel(`Processing: ${formatProcessStage(snapshot.current_stage)} (${snapshot.progress_pct}%)`);
      if (snapshot.status === "done") {
        await handleDoneOnce(snapshot);
        return storedJobId;
      }
      if (snapshot.status === "error") {
        handleErrorOnce(snapshot.error || "Upload processing failed.", snapshot);
        return storedJobId;
      }
      attachToJob(storedJobId, 0);
      return storedJobId;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        clearPersistedJobId();
      }
      setUploadLoadingLabel("");
      if (!(error instanceof ApiError && error.status === 404)) {
        throw error;
      }
      return null;
    }
  }, [
    activeProcessJobStorageKey,
    attachToJob,
    clearPersistedJobId,
    getProcessJobSnapshot,
    handleDoneOnce,
    handleErrorOnce,
    legacyActiveProcessJobStorageKey,
  ]);

  return {
    appendProcessChat,
    attachToJob,
    clearPersistedJobId,
    job,
    liveEnrichedSlides,
    persistJobId,
    processChat,
    reset,
    resumePersistedJob,
    setJob,
    setProcessChat,
    setUploadLoadingLabel,
    stop,
    uploadLoadingLabel,
  };
}
