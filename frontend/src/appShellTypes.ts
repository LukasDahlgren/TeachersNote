import type { ProcessResult, Segment } from "./types";

export type LectureData = ProcessResult & {
  name?: string;
  lecture_id?: number;
  course_id?: string | null;
  course_display?: string | null;
  is_saved?: boolean;
};

export type MainView =
  | { view: "empty" }
  | { view: "upload"; loading: boolean; error?: string }
  | { view: "results"; data: LectureData; activeSlide: number; lectureId?: number };

export interface WorkspaceActiveSlideComputed {
  data: LectureData;
  activeSlide: number;
  segments: Segment[];
  isEnriching: boolean;
}
