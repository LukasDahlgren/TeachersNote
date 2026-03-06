# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack lecture processing platform: upload PDF slides + recording, extract slide text, transcribe audio/video via Groq Whisper, align transcript segments to slides via Claude Sonnet, enrich notes via configurable provider/model (Anthropic default), and generate an enhanced PPTX.

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
npm install
npm run dev                   # Dev server on :5173
npm run build                 # tsc -b && vite build -> dist/
npm run lint                  # ESLint check
```

### Tests
```bash
# from repo root
python3 -m unittest discover -s backend/tests -v
```

Some tests are intentionally skipped when optional dependencies are unavailable in the current environment.

## Architecture

### Data Flow (`POST /process` and `/process/jobs`)
1. Upload PDF + recording (`audio` file XOR `audio_url`) to temporary upload staging.
2. For non-admin users, hash the PDF and check for an approved, non-archived, non-deleted lecture with the same `pdf_hash`.
3. If a reusable lecture exists, grant access to that existing lecture, auto-save it for the uploader, and skip the AI pipeline entirely.
4. Otherwise **parse slides** via `scripts/parse_slides.py`.
5. **Normalize audio** to mono 16k MP3 using FFmpeg.
6. **Transcribe** with Groq Whisper in `backend/pipeline.py`.
7. **Align** transcript to slides using `scripts/align.py` helpers and Anthropic Claude (`ALIGN_MODEL=sonnet|haiku`, default sonnet).
8. **Enrich** slide notes using `scripts/enrich.py` provider abstraction with bounded parallel workers and retries.
9. **Generate PPTX** using `scripts/generate_presentation.py`.
10. **Persist** lecture/slides/transcript/alignment/enrichment to MySQL via async SQLAlchemy.

### Backend (`backend/`)
- `main.py` - FastAPI app and route handlers.
- `pipeline.py` - parse/transcribe/align/enrich/generate orchestration.
- `auth.py` - JWT create/verify + auth dependencies.
- `db.py` + `models.py` - async SQLAlchemy session setup and ORM models.
- `catalog_sync.py` - DSV catalog import/sync logic.
- `media_download.py` - remote recording URL validation + streaming download.
- In-memory job stores support async processing and regeneration with SSE progress.
- Lecture visibility for non-admins is uploader-only unless access is granted through the `lecture_access` table.

### Route Families (current)
- **Auth:** `/auth/register`, `/auth/login`, `/auth/me`
- **Processing:** `/process`, `/process/jobs`, `/process/jobs/{job_id}`, `/process/jobs/{job_id}/events`
- **Lectures:** `/lectures`, `/lectures/my`, `/lectures/deleted`, `/lectures/{id}`, save/unsave, archive, trash, restore, approve, reject, regenerate-notes sync + async job routes
- **Profile:** `/profile`, `/profile/program`, `/profile/courses`, `/profile/course-options`
- **Programs/Admin Catalog:** `/programs`, `/admin/programs*`, `/admin/courses*`, `/admin/programs/{program_id}/courses*`, `/admin/programs/{program_id}/plan`, `/admin/catalog/sync`, `/admin/pending`, `/admin/register`
- **Assets/Utility:** `/health`, `/demo`, `/pdf/{filename}`, `/download/{filename}`

Auth boundary notes:
- Most protected routes require `Authorization: Bearer <token>`.
- `/pdf/{filename}`, `/download/{filename}`, and regeneration SSE endpoints use query-token auth (`?token=<jwt>`), which is required for `EventSource` and asset URL access.
- `/pdf/{filename}` and `/download/{filename}` also enforce lecture-level access; a valid token alone is not enough.
- `/process/jobs/{job_id}` and `/process/jobs/{job_id}/events` are restricted to the upload job owner.
- Regular users can access only lectures they uploaded themselves or lectures unlocked through duplicate-upload reuse; approval no longer makes a lecture globally visible.
- `/demo` is admin-only and returns the newest visible lecture named `IB133N-lecture-14-2026` from DB records.

### Frontend (`frontend/src/`)
- `App.tsx` - auth-aware app shell, routes (`/`, `/lectures/:id`, `/admin`, `/profile`), lecture selection, process/regeneration job state.
- `api.ts` - typed API wrappers for auth, lecture lifecycle, async process jobs + SSE, regeneration jobs + SSE, profile, and admin/catalog operations.
- `types.ts` - shared interfaces including `UploadRecordingInput`, `UploadProcessJobStatus`, `RegenerateNotesJobStatus`, `StudentProfile`, `TeachersNoteSummary`.
- `components/` - upload flow, results view, transcript/slide viewers, admin panel, profile setup, auth pages, dialogs.
- Upload completion can now return `reused_existing=true`, which means the user unlocked an already-generated lecture/PPTX instead of running the pipeline.

## Scripts (`scripts/`) - Import Guidance

- **`parse_slides.py`** - Safe to import: `from scripts.parse_slides import parse_slides`
- **`align.py`** - Use `build_prompt()` and `parse_response()` helpers from pipeline integration
- **`enrich.py`** - Swedish-language enrichment prompts, provider abstraction (`anthropic`/`groq`), retry/fallback normalization helpers

## Environment

Credentials are loaded from `backend/.env` (or process env):

```text
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME     # MySQL connection
JWT_SECRET_KEY                                      # Required JWT signing key
ADMIN_SECRET                                        # Required for /admin/register
ALLOWED_ORIGINS                                     # CORS origins (default: http://localhost:5173)
ANTHROPIC_API_KEY                                   # Required for alignment + Anthropic enrichment
GROQ_API_KEY                                        # Required for transcription + Groq enrichment
ENRICH_PROVIDER                                     # anthropic|groq (default anthropic)
ENRICH_MODEL                                        # Optional model override
ENRICH_MODEL_ANTHROPIC                              # Default: claude-haiku-4-5
ENRICH_MODEL_GROQ                                   # Default: openai/gpt-oss-20b
ENRICH_MAX_WORKERS                                  # Default 2 (example env sets 4)
ENRICH_GLOBAL_MAX_CONCURRENT                        # Default 3
ENRICH_MAX_TRANSCRIPT_WORDS                         # Default 700
ENRICH_MAX_OUTPUT_TOKENS                            # Default 320
ENRICH_MAX_ATTEMPTS                                 # Default 4
ENRICH_LOG_USAGE                                    # Default true
TRANSCRIBE_MODEL                                    # Default whisper-large-v3-turbo
TRANSCRIBE_TARGET_BITRATE                           # Default 32k
TRANSCRIBE_MAX_UPLOAD_BYTES                         # Default 24000000
TRANSCRIBE_CHUNK_HEADROOM_PCT                       # Default 90
TRANSCRIBE_MIN_CHUNK_SECONDS                        # Default 300
TRANSCRIBE_RETRY_ATTEMPTS                           # Default 3
TRANSCRIBE_RETRY_BASE_DELAY_SECONDS                 # Default 3
ALIGN_MODEL                                         # sonnet|haiku (default sonnet)
ALIGN_MAX_TRANSCRIPT_SEGMENTS                       # Default 450
ALIGN_MAX_SEGMENT_CHARS                             # Default 180
ALIGN_MAX_SLIDE_CHARS                               # Default 1200
DISABLE_EXTERNAL_AI                                 # If true, regeneration uses deterministic fallback
REMOTE_MEDIA_ALLOWED_EXTENSIONS                     # Default .mp4,.mov,.webm,.wav,.m4a,.mp3
REMOTE_MEDIA_MAX_BYTES                              # Default 524288000
REMOTE_MEDIA_CONNECT_TIMEOUT_SEC                    # Default 10
REMOTE_MEDIA_READ_TIMEOUT_SEC                       # Default 120
REMOTE_MEDIA_TOTAL_TIMEOUT_SEC                      # Default 600
REGENERATE_NOTES_JOB_TTL_SECONDS                    # Default 1800
PROCESS_UPLOAD_JOB_TTL_SECONDS                      # Default 1800
```

Model choices by stage:
- Transcription: Groq Whisper (`whisper-large-v3-turbo`)
- Alignment: Anthropic Claude Sonnet (`claude-sonnet-4-6`) by default; set `ALIGN_MODEL=haiku` for Claude Haiku (`claude-haiku-4-5`)
- Enrichment: Anthropic by default (`claude-haiku-4-5`), or Groq via `ENRICH_PROVIDER=groq` with optional `ENRICH_MODEL`

## Sample Artifacts (`out/`)

`out/` contains sample Swedish lecture artifacts (`slides.json`, `transcript.json`, `aligned.json`, `enhanced.json`) for local inspection/testing workflows. The `/demo` endpoint itself serves DB-backed lecture content, not direct file reads from `out/`.
