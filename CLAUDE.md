# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack lecture processing platform: extract PDF slide text, transcribe audio/video recordings via Groq Whisper, align transcript segments to slides via Claude Sonnet, enrich slide notes via a configurable provider/model (Anthropic default), and generate enhanced PPTX output.

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

No automated test suite. Manual testing includes `GET /demo` against stored lecture `IB133N-lecture-14-2026`.

## Architecture

### Data Flow (POST /process)
1. Upload PDF + audio/video (file upload or `audio_url` direct link) → `uploads/` temp storage
2. **Parse slides** — `scripts/parse_slides.py` → text from PDF pages
3. **Normalize audio** — FFmpeg converts to mono 16k low-bitrate MP3
4. **Transcribe** — Groq Whisper (`whisper-large-v3-turbo`) in `pipeline.py` → segments
5. **Align** — Claude Sonnet 4.6 via `scripts/align.py` helpers → segments mapped to slides
6. **Enrich** — Configurable provider/model via `scripts/enrich.py` with parallel retry workers in `pipeline.py` (default: Anthropic `claude-haiku-4-5`; optional Groq override), truncation-aware retry, then deterministic fallback if still invalid → summaries + takeaways (Swedish prompts)
7. **Generate** — `scripts/generate_presentation.py` → PPTX in `generated/`
8. **Persist** — SQLAlchemy async → MySQL (lecture + slides + segments + alignment + enrichment)

### Backend (`backend/`)
- `main.py` — FastAPI app; routes:
  - `GET /health`
  - `GET /demo`
  - `GET /pdf/{filename}`, `GET /download/{filename}`
  - `POST /process` (sync), `POST /process/jobs` (async), `GET /process/jobs/{job_id}`, `GET /process/jobs/{job_id}/events` (SSE)
  - `GET /lectures`, `GET /lectures/my`, `GET /lectures/{lecture_id}`
  - `PUT /lectures/{lecture_id}/save`, `DELETE /lectures/{lecture_id}/save`
  - `POST /lectures/{lecture_id}/archive`
  - `POST /lectures/{lecture_id}/regenerate-notes` (sync), `POST /lectures/{lecture_id}/regenerate-notes/jobs` (async), `GET /lectures/regenerate-notes/jobs/{job_id}`, `GET /lectures/regenerate-notes/jobs/{job_id}/events` (SSE)
- `media_download.py` — Remote URL download support: validates HTTPS direct-link URLs, streams to disk with size/timeout limits, redacts URLs in logs. Supports `audio_url` form field as alternative to file upload.
- `pipeline.py` — Orchestrates parse/transcribe/align/enrich/generate
- `db.py` + `models.py` — Async SQLAlchemy setup + ORM models (Lecture, Slide, TranscriptSegment, Alignment, EnrichedSlide)
- CORS configured for `http://localhost:5173`
- Startup initializes DB tables via `lifespan`
- Job system: async processing via in-memory job stores (`UPLOAD_JOB_STORE`, `REGEN_JOB_STORE`) with SSE progress streaming and TTL cleanup

### Frontend (`frontend/src/`)
- `App.tsx` — Main state (`empty` / `upload` / `results`), lecture list loading, active slide handling
- `api.ts` — `checkHealth()`, `processFiles()`, `getLectures()`, `getLecture()` fetch wrappers
- `types.ts` — Shared interfaces: `Slide`, `Segment`, `Alignment`, `EnrichedSlide`, `ProcessResult`, `TeachersNoteSummary`
- `components/` — `UploadForm`, `Sidebar`, `SlideViewer`, `TranscriptPanel`, `ErrorBoundary`

### Scripts (`scripts/`) — Critical import rules
- **`parse_slides.py`** — Safe to import: `from scripts.parse_slides import parse_slides`
- **`align.py`** — Use `build_prompt()` + `parse_response()` helpers from `pipeline.py`
- **`enrich.py`** — Swedish language prompts; provider abstraction (`anthropic` or `groq`) + deterministic prompt truncation + usage logging

## Environment

Credentials are loaded from `backend/.env`:
```
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME   # MySQL connection
ANTHROPIC_API_KEY                                   # Claude API
GROQ_API_KEY                                        # Groq Whisper API
API_KEY                                             # Required app API key
ENRICH_MAX_WORKERS                                  # Optional; default 4 (keep at 4 — higher values hit Groq/Anthropic rate limits)
ENRICH_MAX_TRANSCRIPT_WORDS                         # Recommended runtime: 500 (code default: 700)
ENRICH_MAX_OUTPUT_TOKENS                            # Recommended runtime: 900 (code default: 320)
ENRICH_MAX_ATTEMPTS                                 # Optional; default 4
ENRICH_LOG_USAGE                                    # Optional; default true
ENRICH_PROVIDER                                     # Optional; anthropic|groq (default anthropic)
ENRICH_MODEL                                        # Optional model override (Anthropic default: claude-haiku-4-5)
TRANSCRIBE_MAX_UPLOAD_BYTES                         # Optional; max bytes per transcription request before chunking (default 24000000)
TRANSCRIBE_CHUNK_HEADROOM_PCT                       # Optional; chunk size safety margin percent (default 90)
TRANSCRIBE_MIN_CHUNK_SECONDS                        # Optional; minimum chunk length in seconds (default 300)
ALIGN_MAX_TRANSCRIPT_SEGMENTS                       # Optional; max transcript rows included in one alignment prompt (default 900)
ALIGN_MAX_SEGMENT_CHARS                             # Optional; max chars per transcript row in alignment prompt (default 180)
ALIGN_MAX_SLIDE_CHARS                               # Optional; max chars per slide text in alignment prompt (default 1200)
DISABLE_EXTERNAL_AI                                 # Optional; if true, enrichment uses deterministic fallback only (no API calls)
REMOTE_MEDIA_ALLOWED_EXTENSIONS                     # Optional; comma-separated (default: .mp4,.mov,.webm,.wav,.m4a,.mp3)
REMOTE_MEDIA_MAX_BYTES                              # Optional; default 524288000 (500 MB)
REMOTE_MEDIA_CONNECT_TIMEOUT_SEC                    # Optional; default 10
REMOTE_MEDIA_READ_TIMEOUT_SEC                       # Optional; default 120
REMOTE_MEDIA_TOTAL_TIMEOUT_SEC                      # Optional; default 600
REGENERATE_NOTES_JOB_TTL_SECONDS                    # Optional; default 1800
PROCESS_UPLOAD_JOB_TTL_SECONDS                      # Optional; default 1800
```

Model choice by stage:
- Transcription: Groq Whisper (`whisper-large-v3-turbo`)
- Alignment: Anthropic Claude Sonnet (`claude-sonnet-4-6`)
- Enrichment: Anthropic by default (`claude-haiku-4-5`), or Groq via `ENRICH_PROVIDER=groq` + `ENRICH_MODEL`

## Sample Data (`out/`)
Swedish SQL/DB lecture artifacts: `slides.json`, `transcript.json`, `aligned.json`, `enhanced.json`.
