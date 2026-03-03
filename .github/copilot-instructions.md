# Copilot Instructions

## Project Overview

TeachersNote is a full-stack lecture processing platform: upload PDF slides + recording, extract slide text, transcribe with Groq Whisper, align with Claude Sonnet, enrich notes with configurable provider/model, and generate an enhanced PPTX.

## Dev Commands

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload    # :8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev                  # :5173
npm run build                # tsc -b && vite build
npm run lint
```

### Tests
```bash
# from repo root
python3 -m unittest discover -s backend/tests -v
```

Some tests are skipped in minimal environments if optional dependencies are missing.

## Architecture

### Pipeline Flow
1. Upload PDF + recording (`audio` XOR `audio_url`).
2. Parse slides via `scripts/parse_slides.py`.
3. Transcribe in `backend/pipeline.py` (Groq Whisper, FFmpeg preprocessing/chunking).
4. Align via `scripts/align.py` prompt/parse helpers.
5. Enrich via `scripts/enrich.py` provider abstraction (`anthropic` default, optional `groq`).
6. Generate PPTX via `scripts/generate_presentation.py`.
7. Persist lecture, slides, transcript, alignments, and enrichment rows.

### Backend (`backend/main.py`) route families
- Auth: `/auth/register`, `/auth/login`, `/auth/me`
- Processing: `/process`, `/process/jobs*` (+ SSE events)
- Lectures: list/detail/save/archive/trash/restore/approve/reject/regenerate routes
- Profile: `/profile*`
- Programs/Admin Catalog: `/programs`, `/admin/programs*`, `/admin/courses*`, mappings, plan, catalog sync, pending
- Utility/assets: `/health`, `/demo`, `/pdf/{filename}`, `/download/{filename}`

Auth boundary notes:
- Most protected routes use bearer auth header.
- SSE and file-serving routes use query token (`?token=<jwt>`) for `EventSource`/asset access.
- `/demo` is authenticated and returns DB-backed lecture data (`IB133N-lecture-14-2026` lookup).

### Frontend (`frontend/src/`)
- `App.tsx` manages auth-aware routes and async job state.
- `api.ts` contains typed wrappers for auth, processing jobs + SSE, regeneration jobs + SSE, lectures, profile, and admin/catalog operations.
- `types.ts` includes key contracts: `UploadRecordingInput`, `UploadProcessJobStatus`, `RegenerateNotesJobStatus`, `StudentProfile`, `TeachersNoteSummary`.

## Script Import Guidance

- **`scripts/parse_slides.py`**: safe import (`parse_slides`).
- **`scripts/align.py`**: use helper functions (`build_prompt`, `parse_response`) from pipeline integration.
- **`scripts/enrich.py`**: use normalization/fallback/provider helpers; prompts are Swedish and output is strict normalized JSON shape.

## Environment

Key vars (see `backend/.env.example` and runtime defaults in code):

```text
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
JWT_SECRET_KEY
ADMIN_SECRET
ALLOWED_ORIGINS
ANTHROPIC_API_KEY
GROQ_API_KEY
ENRICH_PROVIDER, ENRICH_MODEL, ENRICH_MODEL_ANTHROPIC, ENRICH_MODEL_GROQ
ENRICH_MAX_WORKERS, ENRICH_GLOBAL_MAX_CONCURRENT
ENRICH_MAX_TRANSCRIPT_WORDS, ENRICH_MAX_OUTPUT_TOKENS, ENRICH_MAX_ATTEMPTS, ENRICH_LOG_USAGE
TRANSCRIBE_MODEL, TRANSCRIBE_TARGET_BITRATE, TRANSCRIBE_MAX_UPLOAD_BYTES
TRANSCRIBE_CHUNK_HEADROOM_PCT, TRANSCRIBE_MIN_CHUNK_SECONDS
TRANSCRIBE_RETRY_ATTEMPTS, TRANSCRIBE_RETRY_BASE_DELAY_SECONDS
ALIGN_MAX_TRANSCRIPT_SEGMENTS (default 450), ALIGN_MAX_SEGMENT_CHARS, ALIGN_MAX_SLIDE_CHARS
DISABLE_EXTERNAL_AI
REMOTE_MEDIA_ALLOWED_EXTENSIONS, REMOTE_MEDIA_MAX_BYTES
REMOTE_MEDIA_CONNECT_TIMEOUT_SEC, REMOTE_MEDIA_READ_TIMEOUT_SEC, REMOTE_MEDIA_TOTAL_TIMEOUT_SEC
REGENERATE_NOTES_JOB_TTL_SECONDS, PROCESS_UPLOAD_JOB_TTL_SECONDS
```

Stage defaults:
- Transcription: `whisper-large-v3-turbo`
- Alignment: `claude-sonnet-4-6`
- Enrichment default model: `claude-haiku-4-5` (Anthropic provider)
