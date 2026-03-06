import {
  type ArchiveLectureResponse,
  isEnrichedSlideInvalid,
  type LectureDetail,
  type TeachersNoteSummary,
  type ProcessResult,
  type UploadLectureNamingInput,
  type UploadRecordingInput,
} from "../types";
import { ApiError, apiFetch, getBaseUrl, readBody } from "./client";

export async function processFiles(
  pdf: File,
  recording: UploadRecordingInput,
  naming?: UploadLectureNamingInput,
  courseContext?: string | null,
): Promise<ProcessResult> {
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
  const res = await apiFetch("/process", { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${getBaseUrl()}/health`);
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

export async function getLecture(id: number, options?: { includeTranscript?: boolean }): Promise<LectureDetail> {
  const query = options?.includeTranscript ? "?include_transcript=true" : "";
  const res = await apiFetch(`/lectures/${id}${query}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await readBody(res);
    const message = (body as { detail?: string } | null)?.detail || `Request failed (${res.status})`;
    throw new ApiError(res.status, message, body);
  }
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
