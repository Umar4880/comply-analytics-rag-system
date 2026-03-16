# RAG Task 1

A local Retrieval-Augmented Generation (RAG) app with:
- Python backend (FastAPI + SQLite + Qdrant)
- Document ingestion and embedding pipeline
- Next.js frontend for document management and chat

## Project Structure

- `app/` - backend API, ingestion, retrieval, database, tests
- `frontend/` - Next.js UI
- `requirements.txt` - Python dependencies

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- Qdrant running locally (or adjust config to your target host)

## Backend Setup

From project root:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Run API:

```bash
uvicorn app.api.main:app --reload
```

Default backend URL:
- `http://127.0.0.1:8000`

Health check:
- `GET /api/health`

## Frontend Setup

From project root:

```bash
cd frontend
npm install
npm run dev
```

Default frontend URL:
- `http://localhost:3000`

## Main API Endpoints

- `GET /api/health`
- `POST /api/chat`
- `GET /api/sessions/{user_id}`
- `GET /api/sessions/{session_id}/messages`
- `DELETE /api/sessions/{session_id}`
- `GET /api/documents`
- `POST /api/documents/upload`
- `DELETE /api/documents/{doc_id}`

## Notes

- Keep backend running before using chat/upload from frontend.
- Ensure Qdrant is available before ingestion/retrieval operations.
- SQLite database is managed by backend modules under `app/database/`.

## RAG Evaluation (Correctness + Hallucination)

This repo includes an evaluation script to test answer correctness and hallucination behavior.

Files:
- `scripts/evaluate_rag.py` - runs benchmark against `/api/chat` and writes reports
- `app/tests/benchmark.sample.json` - sample benchmark dataset format

### 1) Prepare benchmark data

Copy `app/tests/benchmark.sample.json` and create your own dataset (for example `app/tests/benchmark.json`).

Recommended fields per test case:
- `id`: unique test id
- `question`: user query
- `reference_answer`: gold answer (leave empty for no-answer tests)
- `doc_scope`: optional doc_id to limit retrieval
- `expected_chunk_ids`: optional list for retrieval metrics
- `expect_no_answer`: set `true` for unanswerable cases

### 2) Run evaluation

From project root (backend must already be running):

```bash
python scripts/evaluate_rag.py --benchmark app/tests/benchmark.sample.json
```

### 3) Optional: LLM Judge mode (Gemini)

If `GOOGLE_API_KEY` is set, you can use a model-based judge:

```bash
python scripts/evaluate_rag.py --benchmark app/tests/benchmark.sample.json --use-llm-judge
```

### 4) Output reports

Reports are written to `app/tests/eval_reports/`:
- JSON report with per-case details and aggregate summary
- CSV report for spreadsheet analysis

Metrics included:
- `avg_correctness`
- `avg_faithfulness`
- `hallucination_rate`
- `avg_retrieval_hit_at_k` (if `expected_chunk_ids` provided)
- `avg_retrieval_precision` (if `expected_chunk_ids` provided)
- `avg_retrieval_recall` (if `expected_chunk_ids` provided)
