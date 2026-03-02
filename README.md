# TeachersNote

Full-stack lecture processing platform. Upload a PDF slide deck and an audio/video recording, then run a pipeline that extracts slide text, transcribes speech, aligns transcript segments to slides, enriches slide notes with AI, and generates a downloadable PPTX.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · SQLAlchemy (async) |
| Database | MySQL · aiomysql |
| Frontend | React 19 · TypeScript · Vite |
| AI/LLM | Groq Whisper (`whisper-large-v3-turbo`, transcription) · Anthropic Claude Sonnet 4.6 (alignment) · Enrichment: Anthropic Haiku 4.5 by default (`ENRICH_PROVIDER=anthropic`) or optional Groq model override (`ENRICH_PROVIDER`/`ENRICH_MODEL`) |
| Media tooling | FFmpeg (audio normalization before transcription) |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- MySQL instance
- FFmpeg installed and available on `PATH`

### Environment

Create `backend/.env`:

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=teachersnote
API_KEY=your_api_key
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
# Optional: disables all Anthropic/Groq calls for note regeneration jobs
DISABLE_EXTERNAL_AI=false
# Enrichment tuning (cost/speed)
ENRICH_MAX_WORKERS=4
# Recommended runtime overrides
ENRICH_MAX_TRANSCRIPT_WORDS=500
ENRICH_MAX_OUTPUT_TOKENS=900
ENRICH_MAX_ATTEMPTS=4
ENRICH_LOG_USAGE=true
# Code defaults if unset: ENRICH_MAX_TRANSCRIPT_WORDS=700, ENRICH_MAX_OUTPUT_TOKENS=320
# Optional provider/model override (default provider is anthropic)
# ENRICH_PROVIDER=anthropic
# ENRICH_MODEL=claude-haiku-4-5
# ENRICH_PROVIDER=groq
# ENRICH_MODEL=openai/gpt-oss-20b
# Remote recording URL download limits
REMOTE_MEDIA_MAX_BYTES=524288000
REMOTE_MEDIA_CONNECT_TIMEOUT_SEC=10
REMOTE_MEDIA_READ_TIMEOUT_SEC=120
REMOTE_MEDIA_TOTAL_TIMEOUT_SEC=600
REMOTE_MEDIA_ALLOWED_EXTENSIONS=.mp4,.mov,.webm,.wav,.m4a,.mp3
```

### Database Rename (`lecturesummary` -> `teachersnote`)

Use the migration script to preserve all existing data while moving to the new DB name.

Prerequisites:
- `mysql` and `mysqldump` are installed and available on `PATH`
- Credentials can read/write both source and target DBs

Run:

```bash
./scripts/migrate_db_name_to_teachersnote.sh
```

Optional flags/env:

```bash
# If target DB already has tables and you explicitly want to replace it
./scripts/migrate_db_name_to_teachersnote.sh --force-empty-target

# Override defaults when needed
DB_HOST=localhost \
DB_PORT=3306 \
DB_USER=your_user \
DB_PASSWORD=your_password \
OLD_DB_NAME=lecturesummary \
NEW_DB_NAME=teachersnote \
./scripts/migrate_db_name_to_teachersnote.sh
```

What the script does:
1. Stops if source DB is missing.
2. Stops if target DB already has tables (unless `--force-empty-target`).
3. Creates a backup in `out/db_backups/`.
4. Creates target DB (`teachersnote`) with utf8mb4.
5. Imports all source data into target.
6. Verifies required table presence and row-count parity.

After successful migration:
1. Set `DB_NAME=teachersnote` in `backend/.env`.
2. Restart the backend.
3. Run smoke checks: `GET /health`, `/lectures`, `/programs`, `/courses`, `/profile`.

Rollback:
1. Keep the old `lecturesummary` DB until signoff.
2. Revert `DB_NAME` to `lecturesummary`.
3. Restart the backend to return to the previous database.

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload   # http://localhost:8000
```

Tables are created automatically on startup.

### Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
npm run build   # production build → dist/
npm run lint    # ESLint check
```

If needed, set `VITE_API_URL` to point to a non-default backend URL.
The "Regenerate notes" UI action is disabled by default; set `VITE_ENABLE_REGENERATE_NOTES=true` in frontend env to enable it.

---

## Catalog Sync (IDSV / DSV)

TeachersNote can sync current Stockholm University DSV catalog data directly into:

- `programs`
- `courses`
- `program_courses`
- `program_course_plan`

### Local extractor CLI

```bash
python scripts/collect_idsv_catalog.py --snapshot-date 2026-03-01 --out-dir out
```

Outputs:

- `out/teachersnote_idsv_standalone_courses_<YYYY-MM-DD>.csv`
- `out/teachersnote_idsv_program_courses_<YYYY-MM-DD>.csv`
- `out/teachersnote_idsv_programs_<YYYY-MM-DD>.json`

### Admin sync API

`POST /admin/catalog/sync` (admin + API key required)

Request body:

```json
{
  "snapshot_date": "2026-03-01",
  "dry_run": false
}
```

- `snapshot_date` is optional (defaults to server `today`).
- `dry_run=true` calculates changes without writing to DB.

Response includes counters for created/updated/deactivated programs/courses, mapping adds/removals, plan rows written, and warnings.

### Program plan API

`GET /admin/programs/{program_id}/plan` (admin + API key required)

Returns read-only rows with `term_label`, `group_type`, `group_label`, `course_code`, `course_name_sv`, `course_url`, `display_order`, `snapshot_date`.

### Deactivation policy

When a sync applies:

- Programs missing from the snapshot are set `is_active=false` (soft deactivation).
- Courses missing from the snapshot are set `is_active=false` (soft deactivation).
- Program-course mappings are replaced for programs included in the snapshot.
- Program plan rows are replaced for programs included in the snapshot.

Warnings are returned for incomplete source rows (for example missing `Programöversikt` sections or missing `course_code`).

---

## API Reference

All endpoints are served from `http://localhost:8000`.

### `GET /health`

Health check.

**Response**
```json
{ "status": "ok" }
```

### `GET /demo`

Returns processed data for the stored demo lecture named `DB-lecture-12-2026`.
The endpoint returns the newest lecture with that exact name and a visible PPTX asset.
If no matching lecture exists, the endpoint returns `404`.

### `POST /process`

Run the full processing pipeline for an uploaded PDF and recording. The request is synchronous and returns after processing finishes.

**Request** — `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `pdf` | file | Slide deck as PDF |
| `audio` | file | Audio/video recording (`.mp4`, `.mov`, `.webm`, `.wav`, `.m4a`, `.mp3`, etc.). Required when `audio_url` is not provided. |
| `audio_url` | string | Direct HTTPS media URL to recording (`.mp4`, `.mov`, `.webm`, `.wav`, `.m4a`, `.mp3`). Required when `audio` is not provided. |
| `courseid` | string | Required. Normalized to uppercase (`A-Z0-9-`) |
| `kind` | string | Optional. Free text normalized to lowercase slug (`a-z0-9-`); defaults to `lecture` when omitted or blank |
| `lecture` | string | Required. Normalized to alphanumeric plus dashes (casing preserved) |
| `year` | string | Required. Must be exactly 4 digits |

Lecture names and generated assets follow:

`<COURSEID>-<kind>-<lecture>-<year>`

Examples:
- default kind: `DB-lecture-12-2026`
- custom kind: `DB-presentation-12-2026`

If a generated filename already exists (PPTX in `backend/generated/` or source PDF in `backend/source_pdfs/`), suffixes `-2`, `-3`, ... are appended.

Validation behavior:
- `422` when required multipart fields are missing.
- `400` when normalized `courseid`/`lecture` becomes empty, when non-blank `kind` normalizes to empty, when `year` is not exactly 4 digits, or when recording source validation fails.
- Recording source must be exactly one of `audio` or `audio_url` (xor rule).
- `audio_url` accepts direct media URLs only (not player pages). Query tokens are supported.

**Pipeline steps**
1. Parse slide text from PDF pages
2. Convert recording to mono 16k low-bitrate MP3 with FFmpeg
3. Transcribe with Groq Whisper (`whisper-large-v3-turbo`)
4. Align transcript segments to slides via Claude Sonnet 4.6
5. Enrich each slide via configurable provider/model (`ENRICH_PROVIDER` / `ENRICH_MODEL`) with bounded parallel workers and retries (strict JSON validation, truncation-aware retry for token-capped JSON responses, deterministic fallback if responses remain invalid)
6. Generate enhanced PPTX with speaker notes
7. Persist all data to MySQL
8. Copy original PDF into `backend/source_pdfs/`

**Response** — `200 OK`
```json
{
  "lecture_id": 42,
  "slides": [ { "slide": 1, "text": "..." } ],
  "transcript": [ { "start": 0.0, "end": 4.2, "text": "..." } ],
  "alignment": [ { "slide": 1, "start_segment": 0, "end_segment": 5 } ],
  "enhanced": [
    {
      "slide": 1,
      "summary": "...",
      "slide_content": "...",
      "lecturer_additions": "...",
      "key_takeaways": ["...", "..."]
    }
  ],
  "download_url": "/download/DB-lecture-12-2026.pptx",
  "pdf_url": "/pdf/DB-lecture-12-2026.pdf"
}
```

**Error** — `500` with `{ "detail": "<error message>" }`

### `POST /process/jobs`

Start an asynchronous upload processing job (PDF + recording input). Returns immediately and processes in background.

**Request** — `multipart/form-data` (same fields as `POST /process`: `pdf`, `audio` xor `audio_url`, `courseid`, optional `kind`, `lecture`, `year`)

**Response** — `202 Accepted`
```json
{
  "job_id": "ec56a2f86f4440f7a5dd15c006f7f722",
  "status": "queued",
  "current_stage": "upload",
  "progress_pct": 0,
  "lecture_id": null,
  "error": null,
  "updated_at": "2026-02-27T23:30:00+00:00"
}
```

**Conflict** — `409`
```json
{
  "detail": "Upload processing already in progress",
  "active_job_id": "ec56a2f86f4440f7a5dd15c006f7f722"
}
```

### `GET /process/jobs/{job_id}`

Get the latest snapshot state for an asynchronous upload job.

### `GET /process/jobs/{job_id}/events`

SSE stream for live upload processing events (`progress`, `log`, `done`, `error`).

### `GET /download/{filename}`

Download a generated PPTX file.

### `GET /pdf/{filename}`

Serve an uploaded source PDF copied into `backend/source_pdfs/` (with legacy fallback for older files in `backend/generated/`).

### `GET /lectures`

List visible lectures, newest first. Lectures with missing PPTX assets are excluded.

Visibility:
- non-admin users: approved lectures + their own pending uploads
- admin users: all non-deleted lectures

**Response** — `200 OK`
```json
[
  {
    "id": 42,
    "name": "DB-lecture-12-2026",
    "is_demo": false,
    "course_id": "DB",
    "is_saved": true,
    "pptx_path": "generated/DB-lecture-12-2026.pptx",
    "created_at": "2024-01-15T10:30:00"
  }
]
```

### `GET /lectures/my`

List lectures saved by the current user, newest saved first.

### `PUT /lectures/{lecture_id}/save`

Save a lecture to the current user's personal saved list.

Visibility rules match `GET /lectures/{lecture_id}`.

### `DELETE /lectures/{lecture_id}/save`

Remove a lecture from the current user's personal saved list.

Visibility rules match `GET /lectures/{lecture_id}`.

### `GET /lectures/{lecture_id}`

Retrieve full processed data for a stored lecture.

Visibility:
- non-admin users: approved lectures + their own pending uploads
- admin users: all lectures

Response payload includes `course_id` (normalized course code for lecture matching on homepage).

**Error** — `404` if lecture is not found, not visible to current user, or its PPTX asset is missing.

### `POST /lectures/{lecture_id}/archive`

Set lecture archive state (`?archive=true|false`). Archive is a global lecture state.

**Authorization** — admin only (`403` otherwise).

### `POST /lectures/{lecture_id}/trash`

Soft-delete a lecture globally (`is_deleted=true`).

**Authorization** — admin only (`403` otherwise).

### `POST /lectures/{lecture_id}/restore`

Restore a soft-deleted lecture globally (`is_deleted=false`).

**Authorization** — admin only (`403` otherwise).

### `GET /lectures/deleted`

List soft-deleted lectures.

**Authorization** — admin only (`403` otherwise).

### `GET /profile`

Returns the current user profile (`X-User-Id`) with selected program and selected courses.

### `PUT /profile/program`

Set/replace the current user program.

**Request**
```json
{ "program_id": 1 }
```

Use `null` to clear program.

### `PUT /profile/courses`

Replace the current user selected courses.

**Request**
```json
{ "course_ids": [2, 4, 8] }
```

Unknown or inactive IDs return `400`.

### `GET /profile/course-options`

Returns active programs/courses and program-recommended course subset.

### `GET /admin/programs`
### `POST /admin/programs`
### `PATCH /admin/programs/{program_id}`
### `GET /admin/courses`
### `POST /admin/courses`
### `PATCH /admin/courses/{course_id}`
### `GET /admin/programs/{program_id}/courses`
### `PUT /admin/programs/{program_id}/courses/{course_id}`
### `DELETE /admin/programs/{program_id}/courses/{course_id}`

Program/course catalog and mapping endpoints used by admin panel.

**Authorization** — admin only (`403` otherwise).

### `POST /lectures/{lecture_id}/regenerate-notes`

Regenerate notes for slides with missing/invalid enriched content only, then return refreshed enriched notes.

**Response** — `200 OK`
```json
{
  "lecture_id": 42,
  "regenerated_slides": 3,
  "enhanced": [
    {
      "slide": 1,
      "summary": "...",
      "slide_content": "...",
      "lecturer_additions": "...",
      "key_takeaways": ["...", "..."]
    }
  ]
}
```

**Error** — `404` if lecture is not found.

### `POST /lectures/{lecture_id}/regenerate-notes/jobs`

Start an asynchronous note regeneration job for missing/invalid slide notes.

**Response** — `202 Accepted`
```json
{
  "job_id": "c70c4ff9f2e9470b82e2f01a91d93f64",
  "lecture_id": 42,
  "status": "queued",
  "total_slides": 3,
  "completed_slides": 0,
  "current_slide": null,
  "regenerated_slides": 0,
  "error": null,
  "updated_at": "2026-02-27T22:59:00+00:00"
}
```

### `GET /lectures/regenerate-notes/jobs/{job_id}`

Get current snapshot status of an async regeneration job.

### `GET /lectures/regenerate-notes/jobs/{job_id}/events`

SSE stream for live regeneration progress events (`progress`, `done`, `error`).

---

## Data Models

### DB Tables (MySQL / SQLAlchemy)

| Table | Key columns |
|---|---|
| `lectures` | `id`, `name`, `course_id`, `is_demo`, `is_archived`, `is_deleted`, `is_approved`, `uploaded_by`, `pptx_path`, `pdf_path`, `created_at` |
| `lecture_saves` | `id`, `user_id`, `lecture_id`, `created_at` |
| `slides` | `lecture_id`, `slide_number`, `text` |
| `transcript_segments` | `lecture_id`, `segment_index`, `start_time`, `end_time`, `text` |
| `alignments` | `lecture_id`, `slide_number`, `start_segment`, `end_segment` |
| `enriched_slides` | `lecture_id`, `slide_number`, `summary`, `slide_content`, `lecturer_additions`, `key_takeaways` (JSON) |
| `programs` | `id`, `code`, `name`, `is_active`, `created_at`, `updated_at` |
| `courses` | `id`, `code`, `name`, `is_active`, `created_at`, `updated_at` |
| `program_courses` | `program_id`, `course_id`, `created_at` |
| `student_profiles` | `user_id`, `program_id`, `created_at`, `updated_at` |
| `student_courses` | `user_id`, `course_id`, `created_at` |

---

## Architecture

```
backend/
├── main.py              # FastAPI app + route handlers
├── pipeline.py          # Pipeline orchestration
├── db.py                # Async SQLAlchemy engine + session factory
├── models.py            # ORM models
├── generated/           # Output PPTX files
├── source_pdfs/         # Stored source PDFs for slide rendering/regeneration
└── uploads/             # Temporary upload staging

scripts/
├── parse_slides.py         # PDF -> text by page
├── align.py                # Claude Sonnet alignment prompt + parser
├── enrich.py               # Provider-aware enrichment worker (Anthropic default, optional Groq)
└── generate_presentation.py # PPTX generator (PDF pages + notes)

frontend/src/
├── App.tsx              # App state + routing between upload/results
├── api.ts               # checkHealth(), processFiles(), getLectures(), getLecture()
├── types.ts             # Shared TypeScript types
└── components/
    ├── UploadForm.tsx
    ├── Sidebar.tsx
    ├── SlideViewer.tsx
    ├── TranscriptPanel.tsx
    └── ErrorBoundary.tsx
```

---

## Sample Data

`out/` contains sample artifacts for a Swedish database lecture:

- `slides.json`
- `transcript.json`
- `aligned.json`
- `enhanced.json`

The `Show demo` action uses a stored lecture named `DB-lecture-12-2026`, backed by `backend/generated/DB-lecture-12-2026.pptx`.

---

## Notes

- CORS allows `http://localhost:5173` by default.
- There is currently no automated test suite in the repo.

### Model Choice

- **Transcription**: Groq Whisper (`whisper-large-v3-turbo`)
- **Alignment**: Anthropic Claude Sonnet 4.6 (`claude-sonnet-4-6`)
- **Enrichment**: Anthropic Claude Haiku 4.5 (`claude-haiku-4-5`) by default, or Groq via env override

Example enrichment provider override:

```env
ENRICH_PROVIDER=groq
ENRICH_MODEL=openai/gpt-oss-20b
```
