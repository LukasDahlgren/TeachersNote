interface Props {
  slideText: string;
  slideNumber: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}

export default function SlideViewer({ slideText, slideNumber, total, onPrev, onNext }: Props) {
  return (
    <div className="slide-viewer">
      <div className="slide-header">
        <button onClick={onPrev} disabled={slideNumber === 1}>&#8592;</button>
        <span>Slide {slideNumber} of {total}</span>
        <button onClick={onNext} disabled={slideNumber === total}>&#8594;</button>
      </div>
      <pre className="slide-text">{slideText || "(no text extracted)"}</pre>
    </div>
  );
}
