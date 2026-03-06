import { useCallback, useEffect, useRef, useState } from "react";

import { getRegenerateNotesJob, subscribeRegenerateNotesEvents } from "../api";
import type { RegenerateNotesJobStatus } from "../types";

interface RegenerationJobControllerOptions {
  getRegenerateNotesJobSnapshot?: typeof getRegenerateNotesJob;
  onDone?: (lectureId: number, status: RegenerateNotesJobStatus) => void | Promise<void>;
  onError?: (message: string, status?: RegenerateNotesJobStatus) => void;
  subscribeToRegenerateNotesEvents?: typeof subscribeRegenerateNotesEvents;
}

export function useRegenerationJobController({
  getRegenerateNotesJobSnapshot = getRegenerateNotesJob,
  onDone,
  onError,
  subscribeToRegenerateNotesEvents = subscribeRegenerateNotesEvents,
}: RegenerationJobControllerOptions = {}) {
  const [job, setJob] = useState<RegenerateNotesJobStatus | null>(null);

  const unsubscribeRef = useRef<(() => void) | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (unsubscribeRef.current) {
      unsubscribeRef.current();
      unsubscribeRef.current = null;
    }
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  useEffect(() => stop, [stop]);

  const fail = useCallback((message: string, status?: RegenerateNotesJobStatus) => {
    stop();
    onError?.(message, status);
  }, [onError, stop]);

  const attachToJob = useCallback((jobId: string, lectureId: number) => {
    stop();

    unsubscribeRef.current = subscribeToRegenerateNotesEvents(jobId, {
      onProgress: (event) => {
        setJob(event);
      },
      onDone: (event) => {
        stop();
        setJob(event);
        void onDone?.(lectureId, event);
      },
      onError: (event) => {
        setJob(event);
        fail(event.error || "Regeneration failed.", event);
      },
      onTransportError: () => {
        stop();
        void (async () => {
          try {
            const snapshot = await getRegenerateNotesJobSnapshot(jobId);
            setJob(snapshot);
            if (snapshot.status === "done") {
              await onDone?.(lectureId, snapshot);
              return;
            }
            if (snapshot.status === "error") {
              fail(snapshot.error || "Regeneration failed.", snapshot);
              return;
            }
            reconnectTimerRef.current = window.setTimeout(() => {
              attachToJob(jobId, lectureId);
            }, 1000);
          } catch (error) {
            fail(error instanceof Error ? error.message : String(error));
          }
        })();
      },
    });
  }, [fail, getRegenerateNotesJobSnapshot, onDone, stop, subscribeToRegenerateNotesEvents]);

  const reset = useCallback(() => {
    stop();
    setJob(null);
  }, [stop]);

  return {
    attachToJob,
    job,
    reset,
    stop,
  };
}
