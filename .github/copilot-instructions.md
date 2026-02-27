# Copilot Instructions

## Project Overview

Full-stack lecture processing platform: upload a PDF + audio recording → extract slide text, transcribe audio via Whisper, align transcript to slides via Claude AI, enrich with AI summaries, and generate an enhanced PPTX output.

## Dev Commands

### Backend
```bash
cd backend
uvicorn main:app --reload    # Dev server on :8000
```

### Frontend
```bash
cd frontend
npm run dev                  # Dev server on :5173
npm run build                # tsc -b && vite build → dist/
npm run lint                 # ESLint check
```

No automated test suite. Manual testing via `GET /demo` (uses sample data in `out/`).

## Architecture

### Data Flow (`POST /process`)
1. Upload PDF + audio → `uploads/` temp dir
2. **Parse** — `scripts/parse_slides.py` → text per slide from PDF
3. **Transcribe** — faster-whisper (inlined in `pipeline.py`) → timed segments
4. **Align** — Claude API via `scripts/align.py` helpers → segments mapped to slides
5. **Enrich** — Claude API via `scripts/enrich.py` (8 concurrent workers) → summaries + takeaways
6. **Generate** — `scripts/generate_presentation.py` → PPTX saved to `backend/generated/`
7. **Persist** — Async SQLAlchemy → MySQL (Lecture → Slides + TranscriptSegments + Alignments + EnrichedSlides)

### Backend (`backend/`)
- `main.py` — FastAPI app; routes: `GET /health`, `GET /demo`, `POST /process`, `GET /download/{filename}`, `GET /lectures`, `GET /lectures/{lecture_id}`
- `pipeline.py` — Orchestrates the full pipeline; Whisper transcription is inlined here (not in `scripts/transcribe.py`)
- `db.py` + `models.py` — Async SQLAlchemy setup + ORM models
- CORS configured for `http://localhost:5173`
- DB tables auto-created on startup via `lifespan`

### Frontend (`frontend/src/`)
- `App.tsx` — Two-phase state machine: `{idle | loading | error}` → `results`; health-checks backend on mount
- `api.ts` — `loadDemo()`, `processFiles()`, `checkHealth()` fetch wrappers
- `types.ts` — Shared interfaces: `Slide`, `Segment`, `Alignment`, `ProcessResult`
- `components/` — `UploadForm`, `SlideViewer`, `TranscriptPanel` (transcript auto-syncs to active slide via Alignment data)

## Critical Script Import Rules

- **`scripts/transcribe.py`** — **DO NOT IMPORT**: `argparse` runs at module level and breaks imports. Whisper logic is inlined in `pipeline.py` instead.
- **`scripts/parse_slides.py`** — Safe: `from scripts.parse_slides import parse_slides`
- **`scripts/align.py`** — Use `build_prompt()` + `parse_response()` helpers, **not** `align()` directly (it reads from file paths and hardcodes 27 slides)
- **`scripts/enrich.py`** — Swedish-language AI prompts; concurrent via `ThreadPoolExecutor`

## Environment

`backend/.env`:
```
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME   # MySQL connection
ANTHROPIC_API_KEY                                   # Claude API (claude-sonnet-4-6)
```

## Sample Data

`out/` contains a 27-slide Swedish SQL/DB lecture: `slides.json`, `transcript.json`, `aligned.json`, `enhanced.json`. The `/demo` endpoint reads these files and caches results in the DB on first call.
