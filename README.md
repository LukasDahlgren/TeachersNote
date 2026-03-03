# TeachersNote

Upload a PDF slide deck and an audio/video recording -> extract slide text, transcribe speech, align transcript to slides, enrich notes with AI, and download an enhanced PPTX.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ · FastAPI · SQLAlchemy (async) |
| Database | MySQL · aiomysql |
| Frontend | React 19 · TypeScript · Vite |
| AI/LLM | Groq Whisper (transcription) · Anthropic Claude Sonnet 4.6 (alignment default, switch via `ALIGN_MODEL`) · Anthropic Claude Haiku 4.5 (default enrichment) |
| Media | FFmpeg |

---

## Getting Started

### Docker (recommended)

Copy the example env file and fill in secrets:

```bash
cp backend/.env.example .env
```

Required values in `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
JWT_SECRET_KEY=<random secret>
ADMIN_SECRET=<admin registration secret>
```

Start everything:

```bash
docker-compose up --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000

### Local dev

**Prerequisites:** Python 3.10+, Node.js 18+, MySQL, FFmpeg on `PATH`

```bash
# Backend
cd backend
cp .env.example .env   # fill in values
pip install -r requirements.txt
uvicorn main:app --reload   # http://localhost:8000

# Frontend
cd frontend
npm install
npm run dev     # http://localhost:5173
```

Set `VITE_API_URL` if the backend runs on a non-default URL.

---

## Environment

See `backend/.env.example` for all variables. Key runtime settings:

| Variable | Required | Notes |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Yes | MySQL connection |
| `JWT_SECRET_KEY` | Yes | JWT signing secret; backend fails startup if missing |
| `ANTHROPIC_API_KEY` | Yes | Required for alignment and Anthropic enrichment |
| `GROQ_API_KEY` | Yes | Required for transcription and Groq enrichment |
| `ADMIN_SECRET` | No | Required only if using `POST /admin/register` |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins (default: `http://localhost:5173`) |
| `ENRICH_PROVIDER` | No | `anthropic` (default) or `groq` |
| `ENRICH_MODEL` | No | Provider model override |
| `ENRICH_MODEL_ANTHROPIC` | No | Anthropic default model (default: `claude-haiku-4-5`) |
| `ENRICH_MODEL_GROQ` | No | Groq default model (default: `openai/gpt-oss-20b`) |
| `ENRICH_MAX_WORKERS` | No | Parallel enrichment workers (code default: `2`; `.env.example` sets `4`) |
| `ENRICH_GLOBAL_MAX_CONCURRENT` | No | Global cap on concurrent enrichment API calls (default: `3`) |
| `ENRICH_MAX_TRANSCRIPT_WORDS` | No | Prompt transcript cap (default: `700`) |
| `ENRICH_MAX_OUTPUT_TOKENS` | No | Max model output tokens (default: `320`) |
| `ENRICH_MAX_ATTEMPTS` | No | Retry attempts per slide enrichment (default: `4`) |
| `ENRICH_LOG_USAGE` | No | Emit token usage logs (default: `true`) |
| `TRANSCRIBE_MODEL` | No | Whisper model (default: `whisper-large-v3-turbo`) |
| `TRANSCRIBE_TARGET_BITRATE` | No | FFmpeg compression bitrate (default: `32k`) |
| `TRANSCRIBE_MAX_UPLOAD_BYTES` | No | Max upload bytes before chunking (default: `24000000`) |
| `TRANSCRIBE_CHUNK_HEADROOM_PCT` | No | Size safety margin for chunking (default: `90`) |
| `TRANSCRIBE_MIN_CHUNK_SECONDS` | No | Minimum chunk duration (default: `300`) |
| `TRANSCRIBE_RETRY_ATTEMPTS` | No | Retry attempts for transient transcription failures (default: `3`) |
| `TRANSCRIBE_RETRY_BASE_DELAY_SECONDS` | No | Exponential backoff base delay (default: `3`) |
| `TRANSCRIBE_PARALLEL_WORKERS` | No | Per-job parallel chunk workers (default: `2`) |
| `TRANSCRIBE_GLOBAL_MAX_CONCURRENT` | No | Global cap on concurrent transcription API calls across all user jobs (default: `4`) |
| `TRANSCRIBE_PARALLEL_MIN_CHUNKS` | No | Minimum chunk count required before enabling parallel chunk transcription (default: `2`) |
| `ALIGN_MODEL` | No | Alignment model alias: `sonnet` (default) or `haiku` |
| `ALIGN_MAX_TRANSCRIPT_SEGMENTS` | No | Transcript rows in alignment prompt (default: `450`) |
| `ALIGN_MAX_SEGMENT_CHARS` | No | Max chars per transcript row in alignment prompt (default: `180`) |
| `ALIGN_MAX_SLIDE_CHARS` | No | Max chars per slide text in alignment prompt (default: `1200`) |
| `DISABLE_EXTERNAL_AI` | No | Skip external AI calls during note regeneration and use deterministic fallback |
| `REMOTE_MEDIA_ALLOWED_EXTENSIONS` | No | Allowed direct-link extensions (default: `.mp4,.mov,.webm,.wav,.m4a,.mp3`) |
| `REMOTE_MEDIA_MAX_BYTES` | No | Remote media max size (default: `524288000`) |
| `REMOTE_MEDIA_CONNECT_TIMEOUT_SEC` | No | Remote media connect timeout (default: `10`) |
| `REMOTE_MEDIA_READ_TIMEOUT_SEC` | No | Remote media read timeout (default: `120`) |
| `REMOTE_MEDIA_TOTAL_TIMEOUT_SEC` | No | Remote media total timeout (default: `600`) |
| `REGENERATE_NOTES_JOB_TTL_SECONDS` | No | Async regenerate-job retention TTL (default: `1800`) |
| `PROCESS_UPLOAD_JOB_TTL_SECONDS` | No | Async process-job retention TTL (default: `1800`) |

---

## API Reference

Base URL: `http://localhost:8000`

Authentication modes:
- Most protected endpoints use `Authorization: Bearer <token>`.
- File-serving and SSE endpoints that use `EventSource` require `?token=<jwt>` query parameter.

### Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | Public | Register user account |
| `POST` | `/auth/login` | Public | Login and receive JWT |
| `GET` | `/auth/me` | Bearer | Get current user |

### Processing

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/process` | Bearer | Run full pipeline synchronously |
| `POST` | `/process/jobs` | Bearer | Start async pipeline job |
| `GET` | `/process/jobs/{job_id}` | Bearer | Get async upload job status |
| `GET` | `/process/jobs/{job_id}/events` | Query token | Stream async upload job events (SSE) |

`POST /process` and `POST /process/jobs` accept `multipart/form-data`:

| Field | Required | Description |
|---|---|---|
| `pdf` | Yes | Slide deck PDF |
| `audio` | XOR | Audio/video file upload |
| `audio_url` | XOR | Direct HTTPS media URL |
| `courseid` | Yes | Normalized to `A-Z0-9-` |
| `lecture` | Yes | Alphanumeric + dashes |
| `year` | Yes | Exactly 4 digits |
| `kind` | No | Defaults to `lecture` |

Generated asset stem: `<COURSEID>-<kind>-<lecture>-<year>`

### Lectures

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/lectures` | Bearer | List visible lectures |
| `GET` | `/lectures/my` | Bearer | List current user's saved lectures |
| `GET` | `/lectures/deleted` | Bearer (Admin) | List soft-deleted lectures |
| `GET` | `/lectures/{lecture_id}` | Bearer | Get lecture details |
| `PUT` | `/lectures/{lecture_id}/save` | Bearer | Save lecture to user list |
| `DELETE` | `/lectures/{lecture_id}/save` | Bearer | Remove lecture from user list |
| `POST` | `/lectures/{lecture_id}/archive` | Bearer (Admin) | Set archive state (`archive=true|false` query param) |
| `POST` | `/lectures/{lecture_id}/trash` | Bearer (Admin) | Soft-delete lecture |
| `POST` | `/lectures/{lecture_id}/restore` | Bearer (Admin) | Restore soft-deleted lecture |
| `POST` | `/lectures/{lecture_id}/approve` | Bearer (Admin) | Approve pending lecture |
| `POST` | `/lectures/{lecture_id}/reject` | Bearer (Admin) | Reject pending lecture (marks deleted) |
| `POST` | `/lectures/{lecture_id}/regenerate-notes` | Bearer | Sync note regeneration |
| `POST` | `/lectures/{lecture_id}/regenerate-notes/jobs` | Bearer | Start async note regeneration job |
| `GET` | `/lectures/regenerate-notes/jobs/{job_id}` | Bearer | Get async note regeneration status |
| `GET` | `/lectures/regenerate-notes/jobs/{job_id}/events` | Query token | Stream note regeneration events (SSE) |

### Profile and Catalog

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/profile` | Bearer | Get current profile |
| `PUT` | `/profile/program` | Bearer | Set selected program |
| `PUT` | `/profile/courses` | Bearer | Replace selected courses |
| `GET` | `/profile/course-options` | Bearer | Get program/course picker options |
| `GET` | `/programs` | Bearer | List active programs |

### Admin

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/admin/register` | Bearer | Register current user as admin (requires `ADMIN_SECRET`) |
| `GET` | `/admin/pending` | Bearer (Admin) | List pending lecture uploads |
| `GET` | `/admin/programs` | Bearer (Admin) | List programs |
| `POST` | `/admin/programs` | Bearer (Admin) | Create program |
| `PATCH` | `/admin/programs/{program_id}` | Bearer (Admin) | Update program |
| `GET` | `/admin/courses` | Bearer (Admin) | List courses |
| `POST` | `/admin/courses` | Bearer (Admin) | Create course |
| `PATCH` | `/admin/courses/{course_id}` | Bearer (Admin) | Update course |
| `GET` | `/admin/programs/{program_id}/courses` | Bearer (Admin) | List courses mapped to program |
| `PUT` | `/admin/programs/{program_id}/courses/{course_id}` | Bearer (Admin) | Map course to program |
| `DELETE` | `/admin/programs/{program_id}/courses/{course_id}` | Bearer (Admin) | Unmap course from program |
| `GET` | `/admin/programs/{program_id}/plan` | Bearer (Admin) | Read program course plan |
| `POST` | `/admin/catalog/sync` | Bearer (Admin) | Sync DSV catalog (`dry_run` supported) |

### Other

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | Public | Health check |
| `GET` | `/demo` | Bearer | Return newest visible lecture named `IB133N-lecture-14-2026` |
| `GET` | `/download/{filename}` | Query token | Download generated PPTX |
| `GET` | `/pdf/{filename}` | Query token | Download source PDF |

---

## Data Models

| Table | Key columns |
|---|---|
| `users` | `id`, `uuid`, `email`, `password_hash`, `display_name`, `is_active`, `created_at` |
| `admin_users` | `id`, `user_id`, `registered_at` |
| `lectures` | `id`, `name`, `course_id`, `is_demo`, `is_archived`, `is_deleted`, `is_approved`, `uploaded_by`, `pptx_path`, `pdf_path`, `created_at` |
| `lecture_saves` | `id`, `user_id`, `lecture_id`, `created_at` |
| `slides` | `lecture_id`, `slide_number`, `text` |
| `transcript_segments` | `lecture_id`, `segment_index`, `start_time`, `end_time`, `text` |
| `alignments` | `lecture_id`, `slide_number`, `start_segment`, `end_segment` |
| `enriched_slides` | `lecture_id`, `slide_number`, `summary`, `slide_content`, `lecturer_additions`, `key_takeaways` (JSON) |
| `programs` | `id`, `code`, `name`, `is_active`, `created_at`, `updated_at` |
| `courses` | `id`, `code`, `display_code`, `name`, `is_active`, `created_at`, `updated_at` |
| `program_courses` | `program_id`, `course_id`, `created_at` |
| `program_course_plan` | `id`, `program_id`, `course_id`, `term_label`, `group_type`, `group_label`, `course_code`, `course_name_sv`, `course_url`, `display_order`, `snapshot_date`, `created_at`, `updated_at` |
| `student_profiles` | `user_id`, `program_id`, `created_at`, `updated_at` |
| `student_courses` | `user_id`, `course_id`, `created_at` |

---

## Architecture

```text
backend/
|- main.py              # FastAPI app + route handlers
|- pipeline.py          # Pipeline orchestration (parse/transcribe/align/enrich/generate)
|- auth.py              # JWT auth helpers + dependencies
|- db.py                # Async SQLAlchemy engine + session factory
|- models.py            # ORM models
|- catalog_sync.py      # DSV catalog sync logic
|- media_download.py    # Remote URL validation/download (audio_url support)
|- generated/           # Output PPTX files
|- source_pdfs/         # Stored source PDFs
`- uploads/             # Temporary upload staging

scripts/
|- parse_slides.py            # PDF -> text per page
|- align.py                   # Alignment prompt + parser helpers
|- enrich.py                  # Provider-aware enrichment logic
|- generate_presentation.py   # PPTX generator
`- collect_idsv_catalog.py    # DSV catalog extractor CLI

frontend/src/
|- App.tsx
|- api.ts
|- types.ts
`- components/
   |- LoginPage.tsx / SignupPage.tsx
   |- Homepage.tsx
   |- Sidebar.tsx
   |- UploadForm.tsx / ProcessChat.tsx
   |- SlideViewer.tsx / TranscriptPanel.tsx
   |- ProfilePage.tsx / ProgramPicker.tsx
   |- LectureReviewModal.tsx / RegenerateNotesModal.tsx
   |- AdminPanel.tsx
   `- ErrorBoundary.tsx / ConfirmDialog.tsx / InputDialog.tsx
```

---

## Testing and Notes

- Backend tests live in `backend/tests` and use `unittest`.
- Run from repo root:

```bash
python3 -m unittest discover -s backend/tests -v
```

- Some tests are intentionally skipped in minimal environments when optional dependencies (for example `fastapi` or `sqlalchemy`) are missing.
- CORS origins are controlled by `ALLOWED_ORIGINS`.
- Model defaults by stage:
  - Transcription: Groq Whisper (`whisper-large-v3-turbo`)
  - Alignment: Anthropic Claude Sonnet (`claude-sonnet-4-6`) by default; set `ALIGN_MODEL=haiku` for Claude Haiku (`claude-haiku-4-5`)
  - Enrichment: Anthropic Claude Haiku (`claude-haiku-4-5`) by default, or Groq via `ENRICH_PROVIDER=groq` and optional `ENRICH_MODEL`
