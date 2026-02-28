import {
  type ArchiveLectureResponse,
  isEnrichedSlideInvalid,
  type LectureDetail,
  type LectureSummary,
  type ProcessResult,
  type RegenerateNotesJobEvent,
  type RegenerateNotesJobStartResponse,
  type RegenerateNotesJobStatus,
  type RegenerateNotesResponse,
  type UploadLectureNamingInput,
  type UploadProcessJobEvent,
  type UploadProcessJobStartResponse,
  type UploadProcessJobStatus,
} from "./types";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

function apiHeaders(extra?: Record<string, string>): Record<string, string> {
  return { "X-API-Key": API_KEY, ...extra };
}

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, message: string, data: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function readBody(res: Response): Promise<unknown> {
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }
  try {
    return await res.text();
  } catch {
    return null;
  }
}

function parseEventPayload<T>(evt: Event): T | null {
  try {
    const message = evt as MessageEvent<string>;
    return JSON.parse(message.data) as T;
  } catch {
    return null;
  }
}

export async function processFiles(
  pdf: File,
  audio: File,
  naming: UploadLectureNamingInput,
): Promise<ProcessResult> {
  const form = new FormData();
  form.append("pdf", pdf);
  form.append("audio", audio);
  form.append("courseid", naming.courseid);
  form.append("kind", naming.kind);
  form.append("lecture", naming.lecture);
  form.append("year", naming.year);
  const res = await fetch(`${BASE}/process`, { method: "POST", body: form, headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

export async function getLectures(): Promise<LectureSummary[]> {
  const res = await fetch(`${BASE}/lectures`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getLecture(id: number): Promise<LectureDetail> {
  const res = await fetch(`${BASE}/lectures/${id}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function archiveLecture(id: number): Promise<ArchiveLectureResponse> {
  const res = await fetch(`${BASE}/lectures/${id}/archive`, { method: "POST", headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function unarchiveLecture(id: number): Promise<ArchiveLectureResponse> {
  const res = await fetch(`${BASE}/lectures/${id}/unarchive`, { method: "POST", headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getDemoLecture(): Promise<ProcessResult> {
  const res = await fetch(`${BASE}/demo`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface DemoLectureSelection {
  summary: LectureSummary;
  lecture: ProcessResult & { name: string };
  validNotesCount: number;
}

export async function findBestLectureWithNotesByName(
  nameQuery: string,
): Promise<DemoLectureSelection | null> {
  const normalizedQuery = nameQuery.trim().toLowerCase();
  if (!normalizedQuery) return null;

  const lectures = await getLectures();
  const candidates = lectures
    .filter((lecture) => lecture.name.toLowerCase().includes(normalizedQuery))
    .sort((a, b) => {
      const timeA = Date.parse(a.created_at) || 0;
      const timeB = Date.parse(b.created_at) || 0;
      return timeB - timeA;
    });

  let best: DemoLectureSelection | null = null;
  for (const summary of candidates) {
    const lecture = await getLecture(summary.id);
    const validNotesCount = lecture.enhanced.filter((slide) => !isEnrichedSlideInvalid(slide)).length;
    const next: DemoLectureSelection = { summary, lecture, validNotesCount };

    if (!best) {
      best = next;
      continue;
    }

    if (next.validNotesCount > best.validNotesCount) {
      best = next;
      continue;
    }

    if (next.validNotesCount === best.validNotesCount) {
      const nextCreatedAt = Date.parse(summary.created_at) || 0;
      const bestCreatedAt = Date.parse(best.summary.created_at) || 0;
      if (nextCreatedAt > bestCreatedAt) {
        best = next;
      }
    }
  }

  if (!best || best.validNotesCount === 0) return null;
  return best;
}

export async function regenerateLectureNotes(id: number): Promise<RegenerateNotesResponse> {
  const res = await fetch(`${BASE}/lectures/${id}/regenerate-notes`, { method: "POST", headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function startRegenerateNotesJob(id: number): Promise<RegenerateNotesJobStartResponse> {
  const res = await fetch(`${BASE}/lectures/${id}/regenerate-notes/jobs`, { method: "POST", headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getRegenerateNotesJob(jobId: string): Promise<RegenerateNotesJobStatus> {
  const res = await fetch(`${BASE}/lectures/regenerate-notes/jobs/${jobId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

interface RegenerateNotesEventHandlers {
  onProgress?: (event: RegenerateNotesJobEvent) => void;
  onDone?: (event: RegenerateNotesJobEvent) => void;
  onError?: (event: RegenerateNotesJobEvent) => void;
  onTransportError?: () => void;
}

export function subscribeRegenerateNotesEvents(
  jobId: string,
  handlers: RegenerateNotesEventHandlers,
): () => void {
  const source = new EventSource(`${BASE}/lectures/regenerate-notes/jobs/${jobId}/events?token=${encodeURIComponent(API_KEY)}`);
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
  audio: File,
  naming: UploadLectureNamingInput,
): Promise<UploadProcessJobStartResponse> {
  const form = new FormData();
  form.append("pdf", pdf);
  form.append("audio", audio);
  form.append("courseid", naming.courseid);
  form.append("kind", naming.kind);
  form.append("lecture", naming.lecture);
  form.append("year", naming.year);
  const res = await fetch(`${BASE}/process/jobs`, { method: "POST", body: form, headers: apiHeaders() });
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
  const res = await fetch(`${BASE}/process/jobs/${jobId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

interface ProcessJobEventHandlers {
  onProgress?: (event: UploadProcessJobEvent) => void;
  onDone?: (event: UploadProcessJobEvent) => void;
  onError?: (event: UploadProcessJobEvent) => void;
  onLog?: (event: UploadProcessJobEvent) => void;
  onTransportError?: () => void;
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
  params.set("token", API_KEY);
  const source = new EventSource(`${BASE}/process/jobs/${jobId}/events?${params.toString()}`);
  let closed = false;

  source.addEventListener("progress", (evt) => {
    const payload = parseEventPayload<UploadProcessJobEvent>(evt);
    if (payload) handlers.onProgress?.(payload);
  });

  source.addEventListener("log", (evt) => {
    const payload = parseEventPayload<UploadProcessJobEvent>(evt);
    if (payload) handlers.onLog?.(payload);
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
