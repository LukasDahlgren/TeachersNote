import type {
  RegenerateNotesJobEvent,
  RegenerateNotesJobStartResponse,
  RegenerateNotesJobStatus,
  RegenerateNotesResponse,
  SlideEnrichedEvent,
  UploadLectureNamingInput,
  UploadRecordingInput,
  UploadProcessJobEvent,
  UploadProcessJobStartResponse,
  UploadProcessJobStatus,
} from "../types";
import { ApiError, apiFetch, getBaseUrl, getStoredToken, parseEventPayload, readBody } from "./client";

export async function regenerateLectureNotes(id: number): Promise<RegenerateNotesResponse> {
  const res = await apiFetch(`/lectures/${id}/regenerate-notes`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

interface RegenerateNotesEventHandlers {
  onProgress?: (event: RegenerateNotesJobEvent) => void;
  onDone?: (event: RegenerateNotesJobEvent) => void;
  onError?: (event: RegenerateNotesJobEvent) => void;
  onTransportError?: () => void;
}

export async function startRegenerateNotesJob(id: number): Promise<RegenerateNotesJobStartResponse> {
  const res = await apiFetch(`/lectures/${id}/regenerate-notes/jobs`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getRegenerateNotesJob(jobId: string): Promise<RegenerateNotesJobStatus> {
  const res = await apiFetch(`/lectures/regenerate-notes/jobs/${jobId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function subscribeRegenerateNotesEvents(
  jobId: string,
  handlers: RegenerateNotesEventHandlers,
): () => void {
  const source = new EventSource(`${getBaseUrl()}/lectures/regenerate-notes/jobs/${jobId}/events?token=${encodeURIComponent(getStoredToken() ?? "")}`);
  let closed = false;

  source.addEventListener("progress", (evt) => {
    const payload = parseEventPayload<RegenerateNotesJobEvent>(evt);
    if (payload) handlers.onProgress?.(payload);
  });

  source.addEventListener("done", (evt) => {
    const payload = parseEventPayload<RegenerateNotesJobEvent>(evt);
    if (payload) handlers.onDone?.(payload);
    closed = true;
    source.close();
  });

  source.addEventListener("error", (evt) => {
    const payload = parseEventPayload<RegenerateNotesJobEvent>(evt);
    if (payload) handlers.onError?.(payload);
    closed = true;
    source.close();
  });

  source.onerror = () => {
    if (closed) return;
    handlers.onTransportError?.();
  };

  return () => {
    closed = true;
    source.close();
  };
}

export async function startProcessJob(
  pdf: File,
  recording: UploadRecordingInput,
  naming?: UploadLectureNamingInput,
  courseContext?: string | null,
  customName?: string,
): Promise<UploadProcessJobStartResponse> {
  const form = new FormData();
  form.append("pdf", pdf);
  if (recording.type === "file") {
    form.append("audio", recording.file);
  } else {
    form.append("audio_url", recording.url);
  }
  if (naming) {
    form.append("courseid", naming.courseid);
    form.append("kind", naming.kind);
    form.append("lecture", naming.lecture);
    form.append("year", naming.year);
  }
  if (courseContext) {
    form.append("course_context", courseContext);
  }
  if (customName) {
    form.append("custom_name", customName);
  }
  const res = await apiFetch("/process/jobs", { method: "POST", body: form });
  if (!res.ok) {
    const body = await readBody(res);
    const message = typeof body === "string"
      ? body
      : (body as { detail?: string } | null)?.detail || `Request failed (${res.status})`;
    throw new ApiError(res.status, message, body);
  }
  return res.json();
}

export async function getProcessJob(jobId: string): Promise<UploadProcessJobStatus> {
  const res = await apiFetch(`/process/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

interface ProcessJobEventHandlers {
  onProgress?: (event: UploadProcessJobEvent) => void;
  onDone?: (event: UploadProcessJobEvent) => void;
  onError?: (event: UploadProcessJobEvent) => void;
  onLog?: (event: UploadProcessJobEvent) => void;
  onTransportError?: () => void;
  onSlideEnriched?: (event: SlideEnrichedEvent) => void;
}

interface ProcessJobSubscribeOptions {
  lastEventId?: number;
}

export function subscribeProcessJobEvents(
  jobId: string,
  handlers: ProcessJobEventHandlers,
  options: ProcessJobSubscribeOptions = {},
): () => void {
  const params = new URLSearchParams();
  if (typeof options.lastEventId === "number" && options.lastEventId > 0) {
    params.set("last_event_id", String(options.lastEventId));
  }
  params.set("token", getStoredToken() ?? "");
  const source = new EventSource(`${getBaseUrl()}/process/jobs/${jobId}/events?${params.toString()}`);
  let closed = false;

  source.addEventListener("progress", (evt) => {
    const payload = parseEventPayload<UploadProcessJobEvent>(evt);
    if (payload) handlers.onProgress?.(payload);
  });

  source.addEventListener("log", (evt) => {
    const payload = parseEventPayload<UploadProcessJobEvent>(evt);
    if (payload) handlers.onLog?.(payload);
  });

  source.addEventListener("slide_enriched", (evt) => {
    const payload = parseEventPayload<SlideEnrichedEvent>(evt);
    if (payload) handlers.onSlideEnriched?.(payload);
  });

  source.addEventListener("done", (evt) => {
    const payload = parseEventPayload<UploadProcessJobEvent>(evt);
    if (payload) handlers.onDone?.(payload);
    closed = true;
    source.close();
  });

  source.addEventListener("error", (evt) => {
    const payload = parseEventPayload<UploadProcessJobEvent>(evt);
    if (payload) handlers.onError?.(payload);
    closed = true;
    source.close();
  });

  source.onerror = () => {
    if (closed) return;
    handlers.onTransportError?.();
  };

  return () => {
    closed = true;
    source.close();
  };
}
