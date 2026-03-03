export interface Slide {
  slide: number;
  text: string;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
}

export interface Alignment {
  slide: number;
  start_segment: number;
  end_segment: number;
}

export interface EnrichedSlide {
  slide: number;
  summary: string;
  slide_content: string;
  lecturer_additions: string;
  key_takeaways: string[];
}

export interface UploadLectureNamingInput {
  courseid: string;
  kind: string;
  lecture: string;
  year: string;
}

export type CanonicalLectureKind = "lecture" | "other";

export interface ApproveLectureNamingInput {
  courseid: string;
  kind: CanonicalLectureKind;
  lecture: string;
  year: string;
}

export interface UploadNamingRaw {
  courseid: string | null;
  kind: string | null;
  lecture: string | null;
  year: string | null;
}

export type UploadRecordingInput =
  | { type: "file"; file: File }
  | { type: "url"; url: string };

export interface ProcessResult {
  lecture_id?: number;
  slides: Slide[];
  transcript: Segment[];
  alignment: Alignment[];
  enhanced: EnrichedSlide[];
  download_url: string | null;
  pdf_url?: string | null;
  is_archived?: boolean;
}

export interface TeachersNoteSummary {
  id: number;
  name: string;
  is_demo: boolean;
  is_archived: boolean;
  is_deleted?: boolean;
  is_approved?: boolean;
  course_id: string | null;
  course_display: string | null;
  naming_kind?: string | null;
  naming_lecture?: string | null;
  naming_year?: string | null;
  upload_naming_raw?: UploadNamingRaw | null;
  uploaded_by?: string | null;
  is_saved: boolean;
  pptx_path: string | null;
  pdf_url?: string | null;
  created_at: string;
}

export interface LectureDetail extends ProcessResult {
  lecture_id: number;
  name: string;
  course_id: string | null;
  course_display: string | null;
  naming_kind?: string | null;
  naming_lecture?: string | null;
  naming_year?: string | null;
  upload_naming_raw?: UploadNamingRaw | null;
  is_archived: boolean;
  is_saved: boolean;
}

export interface Program {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Course {
  id: number;
  code: string;
  display_code: string | null;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface StudentProfile {
  user_id: string;
  program: Program | null;
  selected_courses: Course[];
}

export interface ProfileCourseOptions {
  program: Program | null;
  programs: Program[];
  all_courses: Course[];
  program_courses: Course[];
  program_course_groups?: Array<{
    program: Program;
    courses: Course[];
  }>;
}

export interface CatalogSyncRequest {
  snapshot_date?: string;
  dry_run?: boolean;
}

export interface CatalogSyncResult {
  snapshot_date: string;
  standalone_count: number;
  program_count: number;
  program_course_count: number;
  program_plan_rows_written: number;
  programs_created: number;
  programs_updated: number;
  programs_deactivated: number;
  courses_created: number;
  courses_updated: number;
  courses_deactivated: number;
  mappings_added: number;
  mappings_removed: number;
  warnings: string[];
  duration_seconds: number;
  dry_run: boolean;
}

export interface ProgramPlanRow {
  id: number;
  program_id: number;
  course_id: number | null;
  term_label: string;
  group_type: "mandatory" | "optional";
  group_label: string | null;
  course_code: string | null;
  course_name_sv: string;
  course_url: string;
  display_order: number;
  snapshot_date: string | null;
}

export interface ProgramPlanResponse {
  program: Program;
  rows: ProgramPlanRow[];
}

export interface ArchiveLectureResponse {
  id: number;
  name: string;
  is_archived: boolean;
  pptx_path: string | null;
  pdf_path: string | null;
  download_url: string | null;
  pdf_url: string | null;
}

export interface RegenerateNotesResponse {
  lecture_id: number;
  regenerated_slides: number;
  enhanced: EnrichedSlide[];
}

export type RegenerateNotesJobState = "queued" | "running" | "done" | "error";

export interface RegenerateNotesJobStatus {
  job_id: string;
  lecture_id: number;
  status: RegenerateNotesJobState;
  total_slides: number;
  completed_slides: number;
  current_slide: number | null;
  regenerated_slides: number;
  error: string | null;
  updated_at: string;
}

export type RegenerateNotesJobStartResponse = RegenerateNotesJobStatus;
export type RegenerateNotesJobEvent = RegenerateNotesJobStatus;

export type UploadProcessJobState = "queued" | "running" | "done" | "error";

export interface UploadProcessJobStatus {
  job_id: string;
  status: UploadProcessJobState;
  current_stage: string;
  progress_pct: number;
  lecture_id: number | null;
  error: string | null;
  updated_at: string;
}

export interface UploadProcessJobEvent extends UploadProcessJobStatus {
  message?: string;
  event_id?: number;
}

export type UploadProcessJobStartResponse = UploadProcessJobStatus;

export interface AuthUser {
  id: number;
  uuid: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export function isEnrichedSlideInvalid(enriched?: EnrichedSlide | null): boolean {
  if (!enriched) return true;
  const summary = enriched.summary?.trim() ?? "";
  const slideContent = enriched.slide_content?.trim() ?? "";
  const lecturerAdditions = enriched.lecturer_additions?.trim() ?? "";
  const takeaways = Array.isArray(enriched.key_takeaways)
    ? enriched.key_takeaways.filter(Boolean)
    : [];
  return !summary && !slideContent && !lecturerAdditions && takeaways.length === 0;
}
