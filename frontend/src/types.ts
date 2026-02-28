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

export interface LectureSummary {
  id: number;
  name: string;
  is_demo: boolean;
  is_archived: boolean;
  pptx_path: string | null;
  pdf_url?: string | null;
  created_at: string;
}

export interface LectureDetail extends ProcessResult {
  lecture_id: number;
  name: string;
  is_archived: boolean;
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
