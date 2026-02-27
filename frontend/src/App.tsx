import { useEffect, useState, useCallback, useMemo } from "react";
import { checkHealth, processFiles, getLectures, getLecture } from "./api";
import UploadForm from "./components/UploadForm";
import SlideViewer from "./components/SlideViewer";
import TranscriptPanel from "./components/TranscriptPanel";
import Sidebar from "./components/Sidebar";
import ErrorBoundary from "./components/ErrorBoundary";
import type { ProcessResult, LectureSummary } from "./types";

type MainView =
  | { view: "empty" }
  | { view: "upload"; loading: boolean; error?: string }
  | { view: "results"; data: ProcessResult & { name?: string }; activeSlide: number; lectureId?: number };

export default function App() {
  const [mainView, setMainView] = useState<MainView>({ view: "empty" });
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [lectures, setLectures] = useState<LectureSummary[]>([]);
  const [lecturesLoading, setLecturesLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const fetchLectures = useCallback(async () => {
    setLecturesLoading(true);
    try {
      const data = await getLectures();
      setLectures(data);
    } catch {
      // silently fail — sidebar shows empty
    } finally {
      setLecturesLoading(false);
    }
  }, []);

  useEffect(() => {
    checkHealth().then(setBackendOnline);
    fetchLectures();
  }, [fetchLectures]);

  async function handleSubmit(pdf: File, audio: File) {
    setMainView({ view: "upload", loading: true });
    try {
      const data = await processFiles(pdf, audio);
      await fetchLectures();
      setMainView({ view: "results", data, activeSlide: 0 });
      setSelectedId(null);
    } catch (err) {
      setMainView({ view: "upload", loading: false, error: String(err) });
    }
  }

  async function handleSelectLecture(id: number) {
    setSelectedId(id);
    setMainView({ view: "upload", loading: true });
    try {
      const data = await getLecture(id);
      setMainView({ view: "results", data, activeSlide: 0, lectureId: id });
    } catch (err) {
      setMainView({ view: "upload", loading: false, error: String(err) });
    }
  }

  function handleNewLecture() {
    setSelectedId(null);
    setMainView({ view: "upload", loading: false });
  }

  const activeSlideComputed = useMemo(() => {
    if (mainView.view !== "results") return null;
    const { data, activeSlide } = mainView;
    const alignment = data.alignment.find(a => a.slide === activeSlide + 1);
    const segments = alignment
      ? data.transcript.slice(alignment.start_segment, alignment.end_segment + 1)
      : [];
    return { data, activeSlide, segments };
  }, [mainView]);

  const onPrev = useCallback(() => {
    if (mainView.view === "results") setMainView({ ...mainView, activeSlide: mainView.activeSlide - 1 });
  }, [mainView]);

  const onNext = useCallback(() => {
    if (mainView.view === "results") setMainView({ ...mainView, activeSlide: mainView.activeSlide + 1 });
  }, [mainView]);

  return (
    <ErrorBoundary>
    <div className="app-shell">
      <Sidebar
        lectures={lectures}
        loading={lecturesLoading}
        selectedId={selectedId}
        onSelect={handleSelectLecture}
        onNewLecture={handleNewLecture}
      />

      <main className="main-content">
        {backendOnline === false && (
          <div className="banner error">Backend offline — start uvicorn on port 8000.</div>
        )}

        {mainView.view === "empty" && (
          <div className="welcome-state">
            <div className="welcome-icon">📚</div>
            <h2 className="welcome-title">Welcome to LectureSummary</h2>
            <p className="welcome-sub">
              Select a lecture from the sidebar or click{" "}
              <button className="welcome-link-btn" onClick={handleNewLecture}>
                + New Lecture
              </button>{" "}
              to get started.
            </p>
          </div>
        )}

        {mainView.view === "upload" && (
          <>
            <UploadForm onSubmit={handleSubmit} loading={mainView.loading} />
            {mainView.error && (
              <div className="banner error">{mainView.error}</div>
            )}
          </>
        )}

        {mainView.view === "results" && activeSlideComputed && (() => {
          const { data, activeSlide, segments } = activeSlideComputed;

          return (
            <div className="results">
              <div className="results-header">
                <span className="results-lecture-name">{data.name ?? "Lecture"}</span>
                {data.download_url && (
                  <a href={`${import.meta.env.VITE_API_URL || "http://localhost:8000"}${data.download_url}`} download>
                    <button>Download PPTX</button>
                  </a>
                )}
              </div>
              <div className="results-body">
                <SlideViewer
                  slideText={data.slides[activeSlide]?.text ?? ""}
                  slideNumber={activeSlide + 1}
                  total={data.slides.length}
                  onPrev={onPrev}
                  onNext={onNext}
                  pdfUrl={data.pdf_url ? `${import.meta.env.VITE_API_URL || "http://localhost:8000"}${data.pdf_url}` : undefined}
                />
                <TranscriptPanel
                  segments={segments}
                  enriched={data.enhanced?.find(e => e.slide === activeSlide + 1)}
                />
              </div>
            </div>
          );
        })()}
      </main>
    </div>
    </ErrorBoundary>
  );
}
