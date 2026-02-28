# Frontend (LectureSummary)

React + TypeScript + Vite frontend for the LectureSummary pipeline.

## Features

- Upload flow for PDF slides + audio/video recording
- Sidebar listing previously processed lectures
- Results view with:
  - PDF slide rendering (`react-pdf`)
  - Transcript segments per slide
  - AI-enriched notes (`summary`, `slide_content`, `lecturer_additions`, `key_takeaways`)
- Download link for generated PPTX

## Requirements

- Node.js 18+
- Running backend API (default: `http://localhost:8000`)

## Configuration

Optional environment variables:

```bash
VITE_API_URL=http://localhost:8000
VITE_ENABLE_REGENERATE_NOTES=false
```

If not set, the frontend uses `http://localhost:8000`.
`VITE_ENABLE_REGENERATE_NOTES` defaults to disabled (`false`), so the regenerate action is unavailable unless explicitly enabled.

## Development

```bash
npm install
npm run dev
```

App runs at `http://localhost:5173`.

## Build and Lint

```bash
npm run build
npm run lint
```

## Main Files

- `src/App.tsx` — app state and screen transitions (`empty`, `upload`, `results`)
- `src/api.ts` — backend fetch wrappers
- `src/types.ts` — shared TypeScript data contracts
- `src/components/` — UI components (`UploadForm`, `Sidebar`, `SlideViewer`, `TranscriptPanel`, `ErrorBoundary`)
