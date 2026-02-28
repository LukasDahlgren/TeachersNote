# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack lecture processing platform: extract PDF slide text, transcribe audio/video recordings via Groq Whisper, align transcript segments to slides via Claude, enrich slide notes via Claude, and generate enhanced PPTX output.

## Dev Commands

### Backend
```bash
cd backend
pip install -r requirements.txt
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
1. Upload PDF + audio/video → `uploads/` temp storage
2. **Parse slides** — `scripts/parse_slides.py` → text from PDF pages
3. **Normalize audio** — FFmpeg converts to mono 16k low-bitrate MP3
4. **Transcribe** — Groq Whisper (`whisper-large-v3-turbo`) in `pipeline.py` → segments
5. **Align** — Claude Sonnet 4.6 via `scripts/align.py` helpers → segments mapped to slides
6. **Enrich** — Claude Haiku 4.5 via `scripts/enrich.py` (sequential + retry in `pipeline.py`) → summaries + takeaways (Swedish prompts)
7. **Generate** — `scripts/generate_presentation.py` → PPTX in `generated/`
8. **Persist** — SQLAlchemy async → MySQL (lecture + slides + segments + alignment + enrichment)

### Backend (`backend/`)
- `main.py` — FastAPI app; routes: `GET /health`, `GET /demo`, `POST /process`, `GET /download/{filename}`, `GET /pdf/{filename}`, `GET /lectures`, `GET /lectures/{lecture_id}`
- `pipeline.py` — Orchestrates parse/transcribe/align/enrich/generate
- `db.py` + `models.py` — Async SQLAlchemy setup + ORM models (Lecture, Slide, TranscriptSegment, Alignment, EnrichedSlide)
- CORS configured for `http://localhost:5173`
- Startup initializes DB tables via `lifespan`

### Frontend (`frontend/src/`)
- `App.tsx` — Main state (`empty` / `upload` / `results`), lecture list loading, active slide handling
- `api.ts` — `checkHealth()`, `processFiles()`, `getLectures()`, `getLecture()` fetch wrappers
- `types.ts` — Shared interfaces: `Slide`, `Segment`, `Alignment`, `EnrichedSlide`, `ProcessResult`, `LectureSummary`
- `components/` — `UploadForm`, `Sidebar`, `SlideViewer`, `TranscriptPanel`, `ErrorBoundary`

### Scripts (`scripts/`) — Critical import rules
- **`parse_slides.py`** — Safe to import: `from scripts.parse_slides import parse_slides`
- **`align.py`** — Use `build_prompt()` + `parse_response()` helpers from `pipeline.py`
- **`enrich.py`** — Swedish language prompts; script supports concurrent workers, while backend pipeline currently processes sequentially to handle rate limits safely

## Environment

Credentials are loaded from `backend/.env`:
```
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME   # MySQL connection
ANTHROPIC_API_KEY                                   # Claude API
GROQ_API_KEY                                        # Groq Whisper API
```

## Sample Data (`out/`)
Swedish SQL/DB lecture artifacts: `slides.json`, `transcript.json`, `aligned.json`, `enhanced.json`, `enhanced_presentation.pptx`.
