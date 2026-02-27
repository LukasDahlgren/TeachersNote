import { useEffect, useState } from "react";
import { checkHealth, processFiles } from "./api";
import UploadForm from "./components/UploadForm";
import SlideViewer from "./components/SlideViewer";
import TranscriptPanel from "./components/TranscriptPanel";
import type { ProcessResult } from "./types";

type AppState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "results"; data: ProcessResult; activeSlide: number };

export default function App() {
  const [state, setState] = useState<AppState>({ phase: "idle" });
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(setBackendOnline);
  }, []);

  async function handleSubmit(pdf: File, audio: File) {
    setState({ phase: "loading" });
    try {
      const data = await processFiles(pdf, audio);
      setState({ phase: "results", data, activeSlide: 0 });
    } catch (err) {
      setState({ phase: "error", message: String(err) });
    }
  }

  function setSlide(index: number) {
    if (state.phase === "results") {
      setState({ ...state, activeSlide: index });
    }
  }

  const loading = state.phase === "loading";

  return (
    <div className="app">
      {backendOnline === false && (
        <div className="banner error">Backend offline — start uvicorn on port 8000.</div>
      )}

      {(state.phase === "idle" || state.phase === "loading" || state.phase === "error") && (
        <>
          <UploadForm onSubmit={handleSubmit} loading={loading} />
          {state.phase === "error" && (
            <div className="banner error">{state.message}</div>
          )}
        </>
      )}

      {state.phase === "results" && (() => {
        const { data, activeSlide } = state;
        const alignment = data.alignment.find(a => a.slide === activeSlide + 1);
        const segments = alignment
          ? data.transcript.slice(alignment.start_segment, alignment.end_segment + 1)
          : [];

        return (
          <div className="results">
            <div className="results-header">
              <button className="secondary" onClick={() => setState({ phase: "idle" })}>
                ← New upload
              </button>
              <a href={`http://localhost:8000${data.download_url}`} download>
                <button>Download PPTX</button>
              </a>
            </div>
            <div className="results-body">
              <SlideViewer
                slideText={data.slides[activeSlide]?.text ?? ""}
                slideNumber={activeSlide + 1}
                total={data.slides.length}
                onPrev={() => setSlide(activeSlide - 1)}
                onNext={() => setSlide(activeSlide + 1)}
              />
              <TranscriptPanel segments={segments} />
            </div>
          </div>
        );
      })()}
    </div>
  );
}
