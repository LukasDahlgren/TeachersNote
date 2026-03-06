import { buildAssetUrl } from "../api";
import type { MainView, WorkspaceActiveSlideComputed } from "../appShellTypes";
import { formatLectureDisplayName } from "../utils/lectureNaming";
import ResizableSplitPane, { NOTES_PRESENTATION_SPLIT_STORAGE_KEY } from "./ResizableSplitPane";
import SlideViewer from "./SlideViewer";
import TranscriptPanel from "./TranscriptPanel";
import ChatPanel from "./ChatPanel";
import ChatSplitArea from "./ChatSplitArea";

type Banner = { kind: "success" | "error"; text: string } | null;

interface WorkspaceRouteContentProps {
  archiveBanner: Banner;
  archivePending: boolean;
  canShowTrashAction: boolean;
  canToggleArchive: boolean;
  canToggleSaved: boolean;
  chatOpen: boolean;
  demoPreviewActive: boolean;
  deletePending: boolean;
  mainView: MainView;
  onAskAI: (text: string) => void;
  onCollapseChat: () => void;
  onExpandChat: () => void;
  onNewLecture: () => void;
  onNext: () => void;
  onOpenDeleteDialog: () => void;
  onPrev: () => void;
  onToggleArchive: () => void;
  onToggleSaved: () => void;
  prefillText: string | null;
  regenBanner: Banner;
  regeneratingNotes: boolean;
  regenerationProgressText: string;
  saveBanner: Banner;
  savePending: boolean;
  showProcessOverlay: boolean;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  viewState: WorkspaceActiveSlideComputed | null;
}

export default function WorkspaceRouteContent({
  archiveBanner,
  archivePending,
  canShowTrashAction,
  canToggleArchive,
  canToggleSaved,
  chatOpen,
  demoPreviewActive,
  deletePending,
  mainView,
  onAskAI,
  onCollapseChat,
  onExpandChat,
  onNewLecture,
  onNext,
  onOpenDeleteDialog,
  onPrev,
  onToggleArchive,
  onToggleSaved,
  prefillText,
  regenBanner,
  regeneratingNotes,
  regenerationProgressText,
  saveBanner,
  savePending,
  showProcessOverlay,
  sidebarCollapsed,
  toggleSidebar,
  viewState,
}: WorkspaceRouteContentProps) {
  if (mainView.view === "empty") {
    return (
      <div className="welcome-state">
        <div className="welcome-icon">📚</div>
        <h2 className="welcome-title">Welcome to TeachersNote</h2>
        <p className="welcome-sub">
          Select a lecture from the sidebar or click{" "}
          <button className="welcome-link-btn" onClick={onNewLecture}>
            + New Lecture
          </button>{" "}
          to get started.
        </p>
      </div>
    );
  }

  if (mainView.view === "upload") {
    return (
      <div className="workspace-upload-placeholder">
        {mainView.loading ? (
          <p className="workspace-upload-placeholder-status">
            <span className="spinner spinner--dark-sm" /> Upload processing is running. Follow progress in the sidebar.
          </p>
        ) : (
          <>
            <h2 className="workspace-upload-placeholder-title">Start a new lecture from the sidebar</h2>
            <p className="workspace-upload-placeholder-subtitle">
              Click <strong>+ New Lecture</strong> to open the upload form.
            </p>
          </>
        )}
        {mainView.error && (
          <div className="banner error">{mainView.error}</div>
        )}
      </div>
    );
  }

  if (!viewState) {
    return null;
  }

  const { data, activeSlide, segments, isEnriching } = viewState;
  const downloadHref = buildAssetUrl(data.download_url);
  const pdfUrl = buildAssetUrl(data.pdf_url);

  return (
    <div className="results">
      <div className="results-header">
        <button
          className="sidebar-toggle-btn"
          onClick={toggleSidebar}
          title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {sidebarCollapsed ? "›" : "‹"}
        </button>
        <span className="results-lecture-name">{formatLectureDisplayName(data) || "Lecture"}</span>
        {demoPreviewActive && <span className="demo-pill">Demo preview</span>}
        <div className="results-actions">
          {canToggleSaved && (
            <button
              className="secondary"
              onClick={onToggleSaved}
              disabled={savePending || archivePending || regeneratingNotes}
            >
              {savePending
                ? (data.is_saved ? "Removing..." : "Saving...")
                : (data.is_saved ? "Remove from Saved" : "Save")}
            </button>
          )}
          {canToggleArchive && (
            <button
              className="secondary"
              onClick={onToggleArchive}
              disabled={archivePending || savePending || regeneratingNotes}
            >
              {archivePending
                ? (data.is_archived ? "Unarchiving..." : "Archiving...")
                : (data.is_archived ? "Unarchive" : "Archive")}
            </button>
          )}
          {downloadHref && (
            <a href={downloadHref} download>
              <button>Download PPTX</button>
            </a>
          )}
          {canShowTrashAction && (
            <button
              type="button"
              className="secondary danger"
              onClick={onOpenDeleteDialog}
              disabled={archivePending || savePending || regeneratingNotes || deletePending}
              aria-label="Delete lecture"
              title="Delete lecture"
            >
              🗑 Delete
            </button>
          )}
        </div>
      </div>
      {regeneratingNotes && (
        <div className="regen-progress">
          <span className="spinner spinner--dark-sm" />
          <span>{regenerationProgressText}</span>
        </div>
      )}
      {regenBanner && (
        <div className={`banner ${regenBanner.kind}`}>{regenBanner.text}</div>
      )}
      {saveBanner && (
        <div className={`banner ${saveBanner.kind}`}>{saveBanner.text}</div>
      )}
      {archiveBanner && (
        <div className={`banner ${archiveBanner.kind}`}>{archiveBanner.text}</div>
      )}
      <ResizableSplitPane
        className="results-body"
        storageKey={NOTES_PRESENTATION_SPLIT_STORAGE_KEY}
        left={(
          <ChatSplitArea
            chatOpen={chatOpen}
            chatPanel={(
              <ChatPanel
                key={mainView.lectureId ?? mainView.data.lecture_id ?? 0}
                lectureId={mainView.lectureId ?? mainView.data.lecture_id ?? 0}
                expanded={chatOpen}
                onExpand={onExpandChat}
                onCollapse={onCollapseChat}
                prefillText={prefillText}
                consoleVisible={showProcessOverlay}
              />
            )}
            viewer={(
              <SlideViewer
                slideText={data.slides[activeSlide]?.text ?? ""}
                slideNumber={activeSlide + 1}
                total={data.slides.length}
                onPrev={onPrev}
                onNext={onNext}
                pdfUrl={pdfUrl}
              />
            )}
          />
        )}
        right={(
          <TranscriptPanel
            segments={segments}
            enriched={data.enhanced?.find((entry) => entry.slide === activeSlide + 1)}
            isEnriching={isEnriching}
            onAskAI={onAskAI}
            showTranscriptTab={false}
          />
        )}
      />
    </div>
  );
}
