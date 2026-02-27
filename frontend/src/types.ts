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

export interface ProcessResult {
  slides: Slide[];
  transcript: Segment[];
  alignment: Alignment[];
  download_url: string;
}
