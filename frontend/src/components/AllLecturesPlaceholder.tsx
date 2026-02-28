interface AllLecturesPlaceholderProps {
  onGoHome: () => void;
}

export default function AllLecturesPlaceholder({ onGoHome }: AllLecturesPlaceholderProps) {
  return (
    <section className="all-lectures-placeholder">
      <h1>All Lectures</h1>
      <p>
        Coming soon. This page will show lectures other users have added so you can browse
        beyond your own workspace.
      </p>
      <button className="secondary" onClick={onGoHome}>
        Back to Home
      </button>
    </section>
  );
}
