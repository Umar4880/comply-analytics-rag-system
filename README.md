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
