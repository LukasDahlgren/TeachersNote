# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack lecture processing platform: extract PDF slide text, transcribe audio via Whisper, align transcript segments to slides via Claude AI, enrich slides with AI summaries, and generate enhanced PPTX output.

## Dev Commands

### Backend
```bash
cd backend
uvicorn main:app --reload     # Dev server on :8000
```

### Frontend
```bash
cd frontend
npm run dev                   # Dev server on :5173
npm run build                 # tsc -b && vite build → dist/
npm run lint                  # ESLint check
```

No automated test suite. Manual testing via `GET /demo` using sample data in `out/`.

## Architecture

### Data Flow (POST /process)
1. Upload PDF + audio → `uploads/` temp storage
2. **Parse slides** — `scripts/parse_slides.py` → text from PDF pages
3. **Transcribe** — faster-whisper (inlined in `pipeline.py`) → segments
4. **Align** — Claude API via `scripts/align.py` helpers → segments mapped to slides
5. **Enrich** — Claude API via `scripts/enrich.py` (8 concurrent workers) → summaries + takeaways (Swedish prompts)
6. **Generate** — `scripts/generate_presentation.py` → PPTX in `generated/`
7. **Persist** — SQLAlchemy async → MySQL (lecture + slides + segments + alignment + enrichment)

### Backend (`backend/`)
- `main.py` — FastAPI app; routes: `GET /health`, `GET /demo`, `POST /process`, `GET /download/{filename}`, `GET /lectures`, `GET /lectures/{lecture_id}`
- `pipeline.py` — Orchestrates the full pipeline; also inlines Whisper transcription
- `db.py` + `models.py` — Async SQLAlchemy setup + ORM models (Lecture, Slide, TranscriptSegment, Alignment, EnrichedSlide)
- CORS configured for `http://localhost:5173`
- Startup initializes DB tables via `lifespan`

### Frontend (`frontend/src/`)
- `App.tsx` — Two-phase state machine: `{idle | loading | error}` → `results`; checks backend health on mount
- `api.ts` — `loadDemo()`, `processFiles()`, `checkHealth()` fetch wrappers
- `types.ts` — Shared interfaces: `Slide`, `Segment`, `Alignment`, `ProcessResult`
- `components/` — `UploadForm`, `SlideViewer`, `TranscriptPanel` (transcript auto-syncs to active slide via Alignment data)

### Scripts (`scripts/`) — Critical import rules
- **`transcribe.py`** — **DO NOT IMPORT**: argparse runs at module level. Whisper logic is inlined in `pipeline.py` instead.
- **`parse_slides.py`** — Safe to import: `from scripts.parse_slides import parse_slides`
- **`align.py`** — Use `build_prompt()` + `parse_response()` helpers, NOT `align()` directly (it hardcodes 27 slides)
- **`enrich.py`** — Swedish language prompts; concurrent via ThreadPoolExecutor

## Environment

Credentials are loaded from `backend/.env`:
```
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME   # MySQL connection
ANTHROPIC_API_KEY                                   # Claude API
```

## Sample Data (`out/`)
27-slide Swedish SQL/DB lecture: `slides.json`, `transcript.json`, `aligned.json` (cached on first `/demo` call), `enhanced.json`.
