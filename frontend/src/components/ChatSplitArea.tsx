import { useCallback, useRef, useState, type ReactNode } from "react";

interface ChatSplitAreaProps {
  chatOpen: boolean;
  chatPanel: ReactNode;
  viewer: ReactNode;
}

const MIN_PCT = 20;
const MAX_PCT = 75;

export default function ChatSplitArea({ chatOpen, chatPanel, viewer }: ChatSplitAreaProps) {
  const [chatWidth, setChatWidth] = useState(50);
  const [isResizing, setIsResizing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; startW: number; containerW: number } | null>(null);

  const stopDrag = useCallback((handle: HTMLElement, pointerId: number) => {
    if (handle.hasPointerCapture(pointerId)) handle.releasePointerCapture(pointerId);
    dragRef.current = null;
    setIsResizing(false);
  }, []);

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();

    const container = containerRef.current;
    const chatEl = container?.querySelector<HTMLElement>(".slide-area__chat");
    if (!container || !chatEl) return;

    dragRef.current = {
      startX: e.clientX,
      startW: chatEl.offsetWidth,
      containerW: container.offsetWidth,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    setIsResizing(true);

    // Clear any text selection that may have started over PDF text.
    window.getSelection()?.removeAllRanges();
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const { startX, startW, containerW } = dragRef.current;
    const pct = Math.min(MAX_PCT, Math.max(MIN_PCT, ((startW + e.clientX - startX) / containerW) * 100));
    setChatWidth(pct);
  }, []);

  const handlePointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    stopDrag(e.currentTarget, e.pointerId);
  }, [stopDrag]);

  const handlePointerCancel = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    stopDrag(e.currentTarget, e.pointerId);
  }, [stopDrag]);

  const handleLostPointerCapture = useCallback(() => {
    dragRef.current = null;
    setIsResizing(false);
  }, []);

  const className = [
    "slide-area",
    chatOpen ? "slide-area--open" : "",
    isResizing ? "slide-area--resizing" : "",
  ].filter(Boolean).join(" ");

  return (
    <div ref={containerRef} className={className}>
      <div
        className="slide-area__chat"
        style={chatOpen ? { width: `${chatWidth}%`, transition: isResizing ? "none" : undefined } : undefined}
      >
        {chatPanel}
      </div>
      {chatOpen && (
        <div
          className="chat-resize-handle"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerCancel}
          onLostPointerCapture={handleLostPointerCapture}
        />
      )}
      <div className="slide-area__viewer">{viewer}</div>
    </div>
  );
}
