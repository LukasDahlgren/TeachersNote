# TeachersNote

Upload a PDF slide deck and an audio/video recording → extract slide text, transcribe speech, align transcript to slides, enrich notes with AI, download enhanced PPTX.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · SQLAlchemy (async) |
| Database | MySQL · aiomysql |
| Frontend | React 19 · TypeScript · Vite |
| AI/LLM | Groq Whisper (transcription) · Anthropic Claude Sonnet 4.6 (alignment) · Anthropic Claude Haiku 4.5 (enrichment, configurable) |
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
Set `VITE_ENABLE_REGENERATE_NOTES=true` to enable the "Regenerate notes" action in the UI.

---

## Environment

See `backend/.env.example` for all variables. Key ones:

| Variable | Required | Notes |
|---|---|---|
| `DB_HOST/PORT/USER/PASSWORD/NAME` | Yes | MySQL connection |
| `ANTHROPIC_API_KEY` | Yes | Alignment + default enrichment |
| `GROQ_API_KEY` | Yes | Whisper transcription |
| `JWT_SECRET_KEY` | Yes | JWT signing secret |
| `ADMIN_SECRET` | Yes | Guards `POST /admin/register` |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins (default: `http://localhost:5173`) |
| `ENRICH_PROVIDER` | No | `anthropic` (default) or `groq` |
| `ENRICH_MODEL` | No | Model override for enrichment |
| `ENRICH_MAX_WORKERS` | No | Parallel enrichment workers (default: 2) |
| `ENRICH_GLOBAL_MAX_CONCURRENT` | No | Global cap on concurrent enrichment API calls (default: 3) |
| `ENRICH_MAX_TRANSCRIPT_WORDS` | No | Recommended: 500 (default: 700) |
| `ENRICH_MAX_OUTPUT_TOKENS` | No | Recommended: 900 (default: 320) |
| `DISABLE_EXTERNAL_AI` | No | Skip all AI calls, use deterministic fallback |

---

## API Reference

All endpoints served from `http://localhost:8000`. Protected endpoints require `Authorization: Bearer <token>`.

### Auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Register a new user account |
| `POST` | `/auth/login` | Login, returns JWT access token |
| `GET` | `/auth/me` | Get current authenticated user |

### Processing

| Method | Path | Description |
|---|---|---|
| `POST` | `/process` | Run full pipeline synchronously (PDF + audio/video upload) |
| `POST` | `/process/jobs` | Start async pipeline job, returns `job_id` |
| `GET` | `/process/jobs/{job_id}` | Get async job status |
| `GET` | `/process/jobs/{job_id}/events` | SSE stream for job progress |

`POST /process` and `POST /process/jobs` accept `multipart/form-data`:

| Field | Required | Description |
|---|---|---|
| `pdf` | Yes | Slide deck PDF |
| `audio` | XOR | Audio/video file |
| `audio_url` | XOR | Direct HTTPS media URL |
| `courseid` | Yes | Normalized to `A-Z0-9-` |
| `lecture` | Yes | Alphanumeric + dashes |
| `year` | Yes | Exactly 4 digits |
| `kind` | No | Defaults to `lecture` |

Generated asset name pattern: `<COURSEID>-<kind>-<lecture>-<year>`

### Lectures

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/lectures` | User | List visible lectures |
| `GET` | `/lectures/my` | User | List user's saved lectures |
| `GET` | `/lectures/{id}` | User | Get full lecture data |
| `PUT` | `/lectures/{id}/save` | User | Save lecture to personal list |
| `DELETE` | `/lectures/{id}/save` | User | Remove from saved list |
| `POST` | `/lectures/{id}/regenerate-notes` | User | Regenerate missing/invalid slide notes (sync) |
| `POST` | `/lectures/{id}/regenerate-notes/jobs` | User | Start async note regeneration job |
| `GET` | `/lectures/regenerate-notes/jobs/{job_id}` | User | Get regeneration job status |
| `GET` | `/lectures/regenerate-notes/jobs/{job_id}/events` | User | SSE stream for regeneration progress |
| `POST` | `/lectures/{id}/approve` | Admin | Approve a pending lecture |
| `POST` | `/lectures/{id}/reject` | Admin | Reject a pending lecture |
| `POST` | `/lectures/{id}/archive` | Admin | Toggle archive state |
| `POST` | `/lectures/{id}/trash` | Admin | Soft-delete |
| `POST` | `/lectures/{id}/restore` | Admin | Restore soft-deleted |
| `GET` | `/lectures/deleted` | Admin | List soft-deleted lectures |

### Profile

| Method | Path | Description |
|---|---|---|
| `GET` | `/profile` | Get current user profile (program + courses) |
| `PUT` | `/profile/program` | Set selected program |
| `PUT` | `/profile/courses` | Replace selected courses |
| `GET` | `/profile/course-options` | Active programs/courses for picker |

### Admin

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/register` | Register admin user (requires `ADMIN_SECRET`) |
| `GET` | `/admin/pending` | List pending lecture uploads awaiting review |
| `GET/POST/PATCH` | `/admin/programs` | Manage programs |
| `GET/POST/PATCH` | `/admin/courses` | Manage courses |
| `GET/PUT/DELETE` | `/admin/programs/{id}/courses/{id}` | Manage program-course mappings |
| `GET` | `/admin/programs/{id}/plan` | Read program course plan |
| `POST` | `/admin/catalog/sync` | Sync DSV catalog (supports `dry_run`) |

### Other

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/demo` | Return stored demo lecture (`IB133N-lecture-14-2026`) |
| `GET` | `/download/{filename}` | Download generated PPTX |
| `GET` | `/pdf/{filename}` | Serve source PDF |
| `GET` | `/programs` | List active programs |

---

## Data Models

| Table | Key columns |
|---|---|
| `users` | `id`, `uuid`, `email`, `password_hash`, `is_active`, `is_admin` |
| `admin_users` | `id`, `email`, `password_hash` |
| `lectures` | `id`, `name`, `course_id`, `is_demo`, `is_archived`, `is_deleted`, `is_approved`, `uploaded_by`, `pptx_path`, `pdf_path`, `created_at` |
| `lecture_saves` | `id`, `user_id`, `lecture_id`, `created_at` |
| `slides` | `lecture_id`, `slide_number`, `text` |
| `transcript_segments` | `lecture_id`, `segment_index`, `start_time`, `end_time`, `text` |
| `alignments` | `lecture_id`, `slide_number`, `start_segment`, `end_segment` |
| `enriched_slides` | `lecture_id`, `slide_number`, `summary`, `slide_content`, `lecturer_additions`, `key_takeaways` (JSON) |
| `programs` | `id`, `code`, `name`, `is_active` |
| `courses` | `id`, `code`, `name`, `is_active` |
| `program_courses` | `program_id`, `course_id` |
| `program_course_plan` | `program_id`, `term_label`, `group_type`, `course_code`, `display_order`, `snapshot_date` |
| `student_profiles` | `user_id`, `program_id` |
| `student_courses` | `user_id`, `course_id` |

---

## Architecture

```
backend/
├── main.py              # FastAPI app + all route handlers
├── pipeline.py          # Pipeline orchestration (parse/transcribe/align/enrich/generate)
├── auth.py              # JWT auth helpers + user dependency
├── db.py                # Async SQLAlchemy engine + session factory
├── models.py            # ORM models
├── catalog_sync.py      # DSV catalog sync logic
├── media_download.py    # Remote URL download (audio_url support)
├── generated/           # Output PPTX files
├── source_pdfs/         # Stored source PDFs
└── uploads/             # Temporary upload staging

scripts/
├── parse_slides.py              # PDF → text per page
├── align.py                     # Claude Sonnet alignment prompt + parser
├── enrich.py                    # Provider-aware enrichment worker
├── generate_presentation.py     # PPTX generator
└── collect_idsv_catalog.py      # Local DSV catalog extractor CLI

frontend/src/
├── App.tsx
├── api.ts
├── types.ts
└── components/
    ├── LoginPage.tsx / SignupPage.tsx
    ├── Homepage.tsx
    ├── Sidebar.tsx
    ├── UploadForm.tsx / ProcessChat.tsx
    ├── SlideViewer.tsx / TranscriptPanel.tsx
    ├── ProfilePage.tsx / ProgramPicker.tsx
    ├── LectureReviewModal.tsx / RegenerateNotesModal.tsx
    ├── AdminPanel.tsx
    └── ErrorBoundary.tsx / ConfirmDialog.tsx / InputDialog.tsx
```

---

## Notes

- No automated test suite.
- CORS origins configured via `ALLOWED_ORIGINS` env var.
- **Transcription**: Groq Whisper (`whisper-large-v3-turbo`)
- **Alignment**: Anthropic Claude Sonnet 4.6 (`claude-sonnet-4-6`)
- **Enrichment**: Anthropic Claude Haiku 4.5 by default; override with `ENRICH_PROVIDER=groq` + `ENRICH_MODEL`
