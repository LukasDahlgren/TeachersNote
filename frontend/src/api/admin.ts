import type {
  ApproveLectureNamingInput,
  CatalogSyncRequest,
  CatalogSyncResult,
  Course,
  Program,
  ProgramPlanResponse,
  TeachersNoteSummary,
} from "../types";
import { apiFetch } from "./client";

export async function getPendingLectures(): Promise<TeachersNoteSummary[]> {
  const res = await apiFetch("/admin/pending", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function approveLecture(
  id: number,
  naming: ApproveLectureNamingInput,
): Promise<TeachersNoteSummary> {
  const res = await apiFetch(`/lectures/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(naming),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function rejectLecture(id: number): Promise<void> {
  const res = await apiFetch(`/lectures/${id}/reject`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
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
