import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

interface ResizableSplitPaneProps {
  left: ReactNode;
  right: ReactNode;
  className?: string;
  storageKey: string;
  defaultLeftPct?: number;
  minPanePx?: number;
  stackBreakpointPx?: number;
}

const DEFAULT_LEFT_PCT = 55;
const DEFAULT_MIN_PANE_PX = 320;
const DEFAULT_STACK_BREAKPOINT_PX = 900;

export const NOTES_PRESENTATION_SPLIT_STORAGE_KEY = "teachers-note.layout.notes-presentation-split";

function clamp(value: number, min: number, max: number): number {
  if (min > max) return value;
  return Math.min(Math.max(value, min), max);
}

function getBounds(containerWidth: number, minPanePx: number): { min: number; max: number } {
  if (containerWidth <= 0) return { min: 0, max: 100 };
  const minPct = (minPanePx / containerWidth) * 100;
  if (minPct >= 50) return { min: 50, max: 50 };
  return { min: minPct, max: 100 - minPct };
}

function readStoredLeftPct(storageKey: string, fallback: number): number {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return fallback;
    const parsed = Number.parseFloat(raw);
    return Number.isFinite(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export default function ResizableSplitPane({
  left,
  right,
  className,
  storageKey,
  defaultLeftPct = DEFAULT_LEFT_PCT,
  minPanePx = DEFAULT_MIN_PANE_PX,
  stackBreakpointPx = DEFAULT_STACK_BREAKPOINT_PX,
}: ResizableSplitPaneProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const leftPctRef = useRef(defaultLeftPct);
  const [leftPct, setLeftPct] = useState<number>(() => readStoredLeftPct(storageKey, defaultLeftPct));
  const [bounds, setBounds] = useState<{ min: number; max: number }>({ min: 0, max: 100 });
  const [isStacked, setIsStacked] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.innerWidth <= stackBreakpointPx;
  });

  useEffect(() => {
    leftPctRef.current = leftPct;
  }, [leftPct]);

  useEffect(() => {
    setLeftPct(readStoredLeftPct(storageKey, defaultLeftPct));
  }, [storageKey, defaultLeftPct]);

  const saveLeftPct = useCallback((value: number) => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(storageKey, value.toString());
    } catch {
      // Ignore private mode / storage quota errors.
    }
  }, [storageKey]);

  const updateLayoutBounds = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const nextBounds = getBounds(container.getBoundingClientRect().width, minPanePx);
    setBounds(nextBounds);
    setLeftPct((current) => clamp(current, nextBounds.min, nextBounds.max));
  }, [minPanePx]);

  const updateFromClientX = useCallback((clientX: number) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    if (rect.width <= 0) return;
    const rawPct = ((clientX - rect.left) / rect.width) * 100;
    const nextBounds = getBounds(rect.width, minPanePx);
    setLeftPct(clamp(rawPct, nextBounds.min, nextBounds.max));
  }, [minPanePx]);

  const stopDragging = useCallback(() => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    document.body.classList.remove("resizable-split--dragging");
    saveLeftPct(leftPctRef.current);
  }, [saveLeftPct]);

  useEffect(() => {
    const updateStacked = () => {
      setIsStacked(window.innerWidth <= stackBreakpointPx);
    };
    updateStacked();
    window.addEventListener("resize", updateStacked);
    return () => window.removeEventListener("resize", updateStacked);
  }, [stackBreakpointPx]);

  useEffect(() => {
    updateLayoutBounds();
    const container = containerRef.current;
    if (!container) return;

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => {
        updateLayoutBounds();
      });
      observer.observe(container);
    }

    window.addEventListener("resize", updateLayoutBounds);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateLayoutBounds);
    };
  }, [updateLayoutBounds]);

  useEffect(() => {
    if (isStacked) stopDragging();
  }, [isStacked, stopDragging]);

  useEffect(() => {
    return () => {
      document.body.classList.remove("resizable-split--dragging");
    };
  }, []);

  const handleDividerPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (isStacked || event.button !== 0) return;
    event.preventDefault();
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    document.body.classList.add("resizable-split--dragging");
    updateFromClientX(event.clientX);
  }, [isStacked, updateFromClientX]);

  const handleDividerPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    updateFromClientX(event.clientX);
  }, [updateFromClientX]);

  const handleDividerPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    stopDragging();
  }, [stopDragging]);

  const handleDividerKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (isStacked) return;
    const step = event.shiftKey ? 5 : 1;
    let delta = 0;
    if (event.key === "ArrowLeft") delta = -step;
    if (event.key === "ArrowRight") delta = step;
    if (delta === 0) return;

    event.preventDefault();
    const container = containerRef.current;
    if (!container) return;
    const nextBounds = getBounds(container.getBoundingClientRect().width, minPanePx);
    const nextValue = clamp(leftPctRef.current + delta, nextBounds.min, nextBounds.max);
    setLeftPct(nextValue);
    saveLeftPct(nextValue);
  }, [isStacked, minPanePx, saveLeftPct]);

  const rootClassName = ["resizable-split", className, isStacked ? "resizable-split--stacked" : ""]
    .filter(Boolean)
    .join(" ");
  const ariaValueNow = Math.round(clamp(leftPct, bounds.min, bounds.max));

  return (
    <div ref={containerRef} className={rootClassName}>
      <div
        className="resizable-split__pane resizable-split__pane--left"
        style={isStacked ? undefined : { flexBasis: `${leftPct}%` }}
      >
        {left}
      </div>
      {!isStacked && (
        <div
          className="resizable-split__divider"
          role="separator"
          tabIndex={0}
          aria-label="Resize notes panel"
          aria-orientation="vertical"
          aria-valuemin={Math.round(bounds.min)}
          aria-valuemax={Math.round(bounds.max)}
          aria-valuenow={ariaValueNow}
          onPointerDown={handleDividerPointerDown}
          onPointerMove={handleDividerPointerMove}
          onPointerUp={handleDividerPointerUp}
          onPointerCancel={stopDragging}
          onLostPointerCapture={stopDragging}
          onKeyDown={handleDividerKeyDown}
        />
      )}
      <div className="resizable-split__pane resizable-split__pane--right">{right}</div>
    </div>
  );
}
