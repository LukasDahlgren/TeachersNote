# Copilot Instructions

## Project Overview

Full-stack lecture processing platform: upload a PDF + audio recording → extract slide text, transcribe audio via Groq Whisper, align transcript to slides via Claude Sonnet, enrich with configurable AI provider/model (Anthropic default), and generate an enhanced PPTX output.

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
3. **Transcribe** — Groq Whisper (`whisper-large-v3-turbo`) in `pipeline.py` → timed segments
4. **Align** — Claude Sonnet 4.6 via `scripts/align.py` helpers → segments mapped to slides
5. **Enrich** — Configurable provider/model via `scripts/enrich.py` + bounded parallel workers in `pipeline.py` (default: Anthropic `claude-haiku-4-5`; optional Groq override), truncation-aware retry, then deterministic fallback if still invalid → summaries + takeaways
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
- **`scripts/enrich.py`** — Swedish-language AI prompts; provider abstraction (`anthropic` or `groq`) + deterministic transcript truncation + usage logging

## Environment

`backend/.env`:
```
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME   # MySQL connection
ANTHROPIC_API_KEY                                   # Claude API (alignment + default enrichment)
GROQ_API_KEY                                        # Groq API (transcription + optional enrichment provider)
API_KEY                                             # Required app API key
ENRICH_MAX_WORKERS                                  # Optional; default 4
ENRICH_MAX_TRANSCRIPT_WORDS                         # Recommended runtime: 500 (code default: 700)
ENRICH_MAX_OUTPUT_TOKENS                            # Recommended runtime: 900 (code default: 320)
ENRICH_MAX_ATTEMPTS                                 # Optional; default 4
ENRICH_LOG_USAGE                                    # Optional; default true
ENRICH_PROVIDER                                     # Optional; anthropic|groq (default anthropic)
ENRICH_MODEL                                        # Optional model override (Anthropic default: claude-haiku-4-5)
```

Model choice by stage:
- Transcription: Groq Whisper (`whisper-large-v3-turbo`)
- Alignment: Anthropic Claude Sonnet (`claude-sonnet-4-6`)
- Enrichment: Anthropic by default (`claude-haiku-4-5`), or Groq via `ENRICH_PROVIDER=groq` + `ENRICH_MODEL`

## Sample Data

`out/` contains a 27-slide Swedish SQL/DB lecture: `slides.json`, `transcript.json`, `aligned.json`, `enhanced.json`. The `/demo` endpoint reads these files and caches results in the DB on first call.
