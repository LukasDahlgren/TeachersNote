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

export interface ProcessResult {
  slides: Slide[];
  transcript: Segment[];
  alignment: Alignment[];
  enhanced: EnrichedSlide[];
  download_url: string;
  pdf_url?: string;
}

export interface LectureSummary {
  id: number;
  name: string;
  is_demo: boolean;
  pptx_path: string | null;
  created_at: string;
}
