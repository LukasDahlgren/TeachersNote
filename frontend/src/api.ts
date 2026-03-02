import {
  type ArchiveLectureResponse,
  type CatalogSyncRequest,
  type CatalogSyncResult,
  type Course,
  isEnrichedSlideInvalid,
  type LectureDetail,
  type TeachersNoteSummary,
  type ProfileCourseOptions,
  type Program,
  type ProgramPlanResponse,
  type ProcessResult,
  type RegenerateNotesJobEvent,
  type RegenerateNotesJobStartResponse,
  type RegenerateNotesJobStatus,
  type RegenerateNotesResponse,
  type StudentProfile,
  type UploadLectureNamingInput,
  type UploadRecordingInput,
  type UploadProcessJobEvent,
  type UploadProcessJobStartResponse,
  type UploadProcessJobStatus,
} from "./types";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const API_KEY = import.meta.env.VITE_API_KEY ?? "";
const USER_ID_STORAGE_KEY = "teachers-note.user-id";
const LEGACY_USER_ID_STORAGE_KEY = "lecture-summary.user-id";
const DEFAULT_USER_ID = "local-dev-user";

function generateUserId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `user-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export function getCurrentUserId(): string {
  if (typeof window === "undefined") return DEFAULT_USER_ID;
  const existing = window.localStorage.getItem(USER_ID_STORAGE_KEY)?.trim();
  if (existing) return existing;

  const legacy = window.localStorage.getItem(LEGACY_USER_ID_STORAGE_KEY)?.trim();
  if (legacy) {
    window.localStorage.setItem(USER_ID_STORAGE_KEY, legacy);
    window.localStorage.removeItem(LEGACY_USER_ID_STORAGE_KEY);
    return legacy;
  }

  const next = generateUserId();
  window.localStorage.setItem(USER_ID_STORAGE_KEY, next);
  return next;
}

function withAuthHeaders(headers?: HeadersInit): Headers {
  const next = new Headers(headers);
  next.set("X-API-Key", API_KEY);
  next.set("X-User-Id", getCurrentUserId());
  return next;
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${BASE}${path}`, {
    ...init,
    headers: withAuthHeaders(init.headers),
  });
}

export function buildAssetUrl(path?: string | null): string | undefined {
  if (!path) return undefined;

  const target = path.startsWith("http://") || path.startsWith("https://")
    ? path
    : `${BASE}${path}`;
  if (!API_KEY) return target;

  try {
    const url = new URL(target, BASE);
    url.searchParams.set("token", API_KEY);
    return url.toString();
  } catch {
    return target;
  }
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
  recording: UploadRecordingInput,
  naming: UploadLectureNamingInput,
): Promise<ProcessResult> {
  const form = new FormData();
  form.append("pdf", pdf);
  if (recording.type === "file") {
    form.append("audio", recording.file);
  } else {
    form.append("audio_url", recording.url);
  }
  form.append("courseid", naming.courseid);
  form.append("kind", naming.kind);
  form.append("lecture", naming.lecture);
  form.append("year", naming.year);
  const res = await apiFetch("/process", { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await apiFetch("/health");
    return res.ok;
  } catch {
    return false;
  }
}

export async function getLectures(): Promise<TeachersNoteSummary[]> {
  const res = await apiFetch("/lectures", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getMyLectures(): Promise<TeachersNoteSummary[]> {
  const res = await apiFetch("/lectures/my", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getLecture(id: number): Promise<LectureDetail> {
  const res = await apiFetch(`/lectures/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getDeletedLectures(): Promise<TeachersNoteSummary[]> {
  const res = await apiFetch("/lectures/deleted", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function trashLecture(id: number): Promise<void> {
  const res = await apiFetch(`/lectures/${id}/trash`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
}

export async function restoreLecture(id: number): Promise<void> {
  const res = await apiFetch(`/lectures/${id}/restore`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
}

export async function archiveLecture(id: number): Promise<ArchiveLectureResponse> {
  const res = await apiFetch(`/lectures/${id}/archive?archive=true`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function unarchiveLecture(id: number): Promise<ArchiveLectureResponse> {
  const res = await apiFetch(`/lectures/${id}/archive?archive=false`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveLecture(id: number): Promise<TeachersNoteSummary> {
  const res = await apiFetch(`/lectures/${id}/save`, { method: "PUT" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function unsaveLecture(id: number): Promise<TeachersNoteSummary> {
  const res = await apiFetch(`/lectures/${id}/save`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getDemoLecture(): Promise<ProcessResult> {
  const res = await apiFetch("/demo");
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface DemoLectureSelection {
  summary: TeachersNoteSummary;
  lecture: ProcessResult & { name: string };
  validNotesCount: number;
}

export async function findBestLectureWithNotesByExactName(
  lectureName: string,
): Promise<DemoLectureSelection | null> {
  const normalizedName = lectureName.trim().toLowerCase();
  if (!normalizedName) return null;

  const lectures = await getLectures();
  const candidates = lectures
    .filter((lecture) => lecture.name.trim().toLowerCase() === normalizedName)
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
  const res = await apiFetch(`/lectures/${id}/regenerate-notes`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
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

export async function registerAsAdmin(secret: string): Promise<{ status: string; user_id: string }> {
  const res = await apiFetch("/admin/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ secret }),
  });
  if (!res.ok) {
    const body = await readBody(res);
    const message = (body as { detail?: string } | null)?.detail || `Request failed (${res.status})`;
    throw new ApiError(res.status, message, body);
  }
  return res.json();
}

export async function getPendingLectures(): Promise<TeachersNoteSummary[]> {
  const res = await apiFetch("/admin/pending", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function approveLecture(id: number): Promise<TeachersNoteSummary> {
  const res = await apiFetch(`/lectures/${id}/approve`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function rejectLecture(id: number): Promise<void> {
  const res = await apiFetch(`/lectures/${id}/reject`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
}

export async function getProfile(): Promise<StudentProfile> {
  const res = await apiFetch("/profile", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateProfileProgram(programId: number | null): Promise<StudentProfile> {
  const res = await apiFetch("/profile/program", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ program_id: programId }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateProfileCourses(courseIds: number[]): Promise<StudentProfile> {
  const res = await apiFetch("/profile/courses", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ course_ids: courseIds }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getProfileCourseOptions(): Promise<ProfileCourseOptions> {
  const res = await apiFetch("/profile/course-options", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPrograms(): Promise<Program[]> {
  const res = await apiFetch("/admin/programs", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createProgram(payload: {
  code: string;
  name: string;
  is_active?: boolean;
}): Promise<Program> {
  const res = await apiFetch("/admin/programs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateProgram(
  id: number,
  payload: Partial<{ code: string; name: string; is_active: boolean }>,
): Promise<Program> {
  const res = await apiFetch(`/admin/programs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getCourses(): Promise<Course[]> {
  const res = await apiFetch("/admin/courses", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createCourse(payload: {
  code: string;
  display_code?: string | null;
  name: string;
  is_active?: boolean;
}): Promise<Course> {
  const res = await apiFetch("/admin/courses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateCourse(
  id: number,
  payload: Partial<{ code: string; display_code: string | null; name: string; is_active: boolean }>,
): Promise<Course> {
  const res = await apiFetch(`/admin/courses/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface ProgramCoursesResponse {
  program: Program;
  courses: Course[];
}

export async function getProgramCourses(programId: number): Promise<ProgramCoursesResponse> {
  const res = await apiFetch(`/admin/programs/${programId}/courses`, { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function mapProgramCourse(programId: number, courseId: number): Promise<void> {
  const res = await apiFetch(`/admin/programs/${programId}/courses/${courseId}`, { method: "PUT" });
  if (!res.ok) throw new Error(await res.text());
}

export async function unmapProgramCourse(programId: number, courseId: number): Promise<void> {
  const res = await apiFetch(`/admin/programs/${programId}/courses/${courseId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

export async function runCatalogSync(payload: CatalogSyncRequest = {}): Promise<CatalogSyncResult> {
  const res = await apiFetch("/admin/catalog/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getProgramPlan(programId: number): Promise<ProgramPlanResponse> {
  const res = await apiFetch(`/admin/programs/${programId}/plan`, { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function startProcessJob(
  pdf: File,
  recording: UploadRecordingInput,
  naming: UploadLectureNamingInput,
): Promise<UploadProcessJobStartResponse> {
  const form = new FormData();
  form.append("pdf", pdf);
  if (recording.type === "file") {
    form.append("audio", recording.file);
  } else {
    form.append("audio_url", recording.url);
  }
  form.append("courseid", naming.courseid);
  form.append("kind", naming.kind);
  form.append("lecture", naming.lecture);
  form.append("year", naming.year);
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
