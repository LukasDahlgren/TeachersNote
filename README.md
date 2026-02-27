# LectureSummary

Full-stack lecture processing platform. Upload a PDF slide deck and an audio recording → extract slide text, transcribe audio via Whisper, align transcript to slides via Claude AI, enrich with AI summaries, and generate an enhanced PPTX output.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · faster-whisper · Anthropic Claude |
| Database | MySQL · SQLAlchemy (async) |
| Frontend | React 18 · TypeScript · Vite |
| AI | Claude Sonnet (align + enrich) · faster-whisper (transcription) |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- MySQL instance

### Environment

Create `backend/.env`:

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=lecturesummary
ANTHROPIC_API_KEY=sk-ant-...
```

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload   # http://localhost:8000
```

DB tables are created automatically on startup.

### Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
npm run build   # production build → dist/
npm run lint    # ESLint check
```

---

## API Reference

All endpoints are served from `http://localhost:8000`.

---

### `GET /health`

Health check.

**Response**
```json
{ "status": "ok" }
```

---

### `GET /demo`

Returns processed data for the built-in 27-slide Swedish SQL/DB lecture sample. On first call the data is aligned (if `out/aligned.json` is missing) and persisted to the DB; subsequent calls return the cached DB record.

**Response** — `200 OK`
```json
{
  "slides": [
    { "slide": 1, "text": "..." }
  ],
  "transcript": [
    { "start": 0.0, "end": 4.2, "text": "..." }
  ],
  "alignment": [
    { "slide": 1, "start_segment": 0, "end_segment": 5 }
  ],
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

---

### `POST /process`

Run the full pipeline on a new PDF + audio upload. Returns immediately once processing is complete.

**Request** — `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `pdf` | file | Slide deck as PDF |
| `audio` | file | Lecture recording (`.wav`, `.mp3`, etc.) |

**Pipeline steps**
1. Parse slide text from PDF pages
2. Transcribe audio with faster-whisper
3. Align transcript segments to slides via Claude
4. Enrich each slide with summary + takeaways via Claude (8 concurrent workers)
5. Generate enhanced PPTX
6. Persist lecture to DB
7. Copy original PDF to `generated/` for download

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
  "download_url": "/download/<uuid>.pptx",
  "pdf_url": "/pdf/<uuid>.pdf"
}
```

**Error** — `500` with `{ "detail": "<error message>" }`

---

### `GET /download/{filename}`

Download a generated PPTX file.

**Path param** — `filename`: the `.pptx` filename (from `download_url` in the `/process` response)

**Response** — PPTX file attachment (`application/vnd.openxmlformats-officedocument.presentationml.presentation`)

---

### `GET /pdf/{filename}`

Serve the original uploaded PDF.

**Path param** — `filename`: the `.pdf` filename (from `pdf_url`)

**Response** — PDF file (`application/pdf`)

---

### `GET /lectures`

List all stored lectures, newest first.

**Response** — `200 OK`
```json
[
  {
    "id": 42,
    "name": "lecture.pdf",
    "is_demo": false,
    "pptx_path": "generated/<uuid>.pptx",
    "created_at": "2024-01-15T10:30:00"
  }
]
```

---

### `GET /lectures/{lecture_id}`

Retrieve full processed data for a stored lecture.

**Path param** — `lecture_id`: integer lecture ID

**Response** — `200 OK`
```json
{
  "lecture_id": 42,
  "name": "lecture.pdf",
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
  "download_url": "/download/<uuid>.pptx",
  "pdf_url": "/pdf/<uuid>.pdf"
}
```

**Error** — `404` if lecture not found

---

## Data Models

### DB Tables (MySQL / SQLAlchemy)

| Table | Key columns |
|---|---|
| `lectures` | `id`, `name`, `is_demo`, `pptx_path`, `pdf_path`, `created_at` |
| `slides` | `lecture_id`, `slide_number`, `text` |
| `transcript_segments` | `lecture_id`, `segment_index`, `start_time`, `end_time`, `text` |
| `alignments` | `lecture_id`, `slide_number`, `start_segment`, `end_segment` |
| `enriched_slides` | `lecture_id`, `slide_number`, `summary`, `slide_content`, `lecturer_additions`, `key_takeaways` (JSON) |

---

## Architecture

```
backend/
├── main.py           # FastAPI app + all route handlers
├── pipeline.py       # Orchestrates pipeline; inlines Whisper transcription
├── db.py             # Async SQLAlchemy engine + session factory
├── models.py         # ORM models
├── requirements.txt
├── generated/        # PPTX + PDF output files
└── uploads/          # Temp dir for incoming files

scripts/
├── parse_slides.py        # PDF → text per slide
├── align.py               # Claude prompt helpers for alignment
├── enrich.py              # Claude enrichment (Swedish prompts, concurrent)
└── generate_presentation.py  # PPTX generator

frontend/src/
├── App.tsx           # State machine: idle/loading/error → results
├── api.ts            # loadDemo(), processFiles(), checkHealth()
├── types.ts          # Shared TypeScript interfaces
└── components/
    ├── UploadForm.tsx
    ├── SlideViewer.tsx
    └── TranscriptPanel.tsx  # Auto-syncs to active slide via alignment data

out/                  # Sample data (27-slide Swedish DB lecture)
├── slides.json
├── transcript.json
├── aligned.json
└── enhanced.json
```

### Pipeline Detail (`POST /process`)

1. **Parse** — `scripts/parse_slides.py` extracts text per PDF page
2. **Transcribe** — faster-whisper (inlined in `pipeline.py`) → timed segments
3. **Align** — Claude via `scripts/align.py` (`build_prompt` / `parse_response`) → segments mapped to slides
4. **Enrich** — Claude via `scripts/enrich.py` with 8 concurrent workers → `summary`, `slide_content`, `lecturer_additions`, `key_takeaways` per slide
5. **Generate** — `scripts/generate_presentation.py` → PPTX saved to `backend/generated/`
6. **Persist** — all data written to MySQL via async SQLAlchemy

---

## Sample Data

`out/` contains a pre-processed 27-slide Swedish SQL/DB lecture used by the `/demo` endpoint. `aligned.json` is generated on first call if missing; `enhanced.json` is pre-populated.

---

## Notes

- CORS is configured for `http://localhost:5173` (frontend dev server)
- `scripts/transcribe.py` must **not** be imported — its `argparse` runs at module level; Whisper logic is inlined in `pipeline.py` instead
- `scripts/align.py`'s top-level `align()` function hardcodes 27 slides; use `build_prompt()` + `parse_response()` helpers when calling from `pipeline.py`
