import { useRef, useState, useEffect } from "react";
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
  const [pdfErrorByUrl, setPdfErrorByUrl] = useState<{ url: string; message: string } | null>(null);
  const [pdfWidth, setPdfWidth] = useState(600);
  const containerRef = useRef<HTMLDivElement>(null);
  const pdfError = pdfUrl && pdfErrorByUrl?.url === pdfUrl ? pdfErrorByUrl.message : "";

  useEffect(() => {
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;

    const updateWidth = (immediate = false) => {
      if (!containerRef.current) return;
      const width = containerRef.current.offsetWidth - 32;
      const next = Math.max(width, 300);
      if (immediate) {
        if (debounceTimer !== null) { clearTimeout(debounceTimer); debounceTimer = null; }
        setPdfWidth(next);
      } else {
        if (debounceTimer !== null) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => { setPdfWidth(next); debounceTimer = null; }, 120);
      }
    };

    updateWidth(true);

    const container = containerRef.current;
    let observer: ResizeObserver | null = null;
    if (container && typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => updateWidth(false));
      observer.observe(container);
    }

    window.addEventListener("resize", () => updateWidth(false));
    return () => {
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      observer?.disconnect();
      window.removeEventListener("resize", () => updateWidth(false));
    };
  }, [pdfUrl, pdfError]);

  return (
    <div className="slide-viewer">
      <div className="slide-header">
        <button onClick={onPrev} disabled={slideNumber === 1}>&#8592;</button>
        <span>Slide {slideNumber} of {total}</span>
        <button onClick={onNext} disabled={slideNumber === total}>&#8594;</button>
      </div>
      {pdfUrl && !pdfError ? (
        <div className="slide-pdf" ref={containerRef}>
          <Document
            file={pdfUrl}
            loading={<div className="slide-pdf-loading">Loading PDF…</div>}
            onLoadSuccess={() => {
              setPdfErrorByUrl(null);
            }}
            onLoadError={(error) => {
              setPdfErrorByUrl({
                url: pdfUrl,
                message: error instanceof Error ? error.message : String(error),
              });
            }}
          >
            <Page pageNumber={slideNumber} width={pdfWidth} />
          </Document>
        </div>
      ) : pdfUrl && pdfError ? (
        <div className="slide-pdf slide-pdf--error">
          <div className="slide-pdf-error">
            Failed to load PDF. Showing extracted slide text instead.
          </div>
          <pre className="slide-pdf-error-text">{slideText || "(no text extracted)"}</pre>
        </div>
      ) : (
        <pre className="slide-text">{slideText || "(no text extracted)"}</pre>
      )}
    </div>
  );
}
