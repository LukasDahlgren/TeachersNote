import type { ProfileCourseOptions, Program, StudentProfile } from "../types";
import { apiFetch } from "./client";

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

export async function getPublicPrograms(): Promise<Program[]> {
  const res = await apiFetch("/programs", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
