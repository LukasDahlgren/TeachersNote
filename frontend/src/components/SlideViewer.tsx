import { Document, Page } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { ensurePdfWorker } from "../pdfWorker";

ensurePdfWorker();

interface Props {
  slideText: string;
  slideNumber: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
  pdfUrl?: string;
}

export default function SlideViewer({ slideText, slideNumber, total, onPrev, onNext, pdfUrl }: Props) {
  return (
    <div className="slide-viewer">
      <div className="slide-header">
        <button onClick={onPrev} disabled={slideNumber === 1}>&#8592;</button>
        <span>Slide {slideNumber} of {total}</span>
        <button onClick={onNext} disabled={slideNumber === total}>&#8594;</button>
      </div>
      {pdfUrl ? (
        <div className="slide-pdf">
          <Document file={pdfUrl} loading={<div className="slide-pdf-loading">Loading PDF…</div>}>
            <Page pageNumber={slideNumber} width={600} />
          </Document>
        </div>
      ) : (
        <pre className="slide-text">{slideText || "(no text extracted)"}</pre>
      )}
    </div>
  );
}
