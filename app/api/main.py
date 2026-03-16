from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from qdrant_client import QdrantClient

from app.api.models import ChatRequest
from app.database.sql import Database
from app.ingestion.embedder import EmbedDocument
from app.retrieval.pipeline import RetrievalPipeline


def err(error: str, code: str, detail: str | None = None, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "code": code, "detail": detail})


pipeline: RetrievalPipeline | None = None
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "db" / "sql_db.db"
logger = logging.getLogger(__name__)


def get_db_path() -> str:
    return os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    # Ensure the SQL schema exists before API requests hit endpoints.
    Database(db_path=get_db_path())
    pipeline = RetrievalPipeline()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    sql_ok = False
    qdrant_ok = False
    ollama_ok = False

    db_path = get_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()
        sql_ok = True
    except Exception:
        sql_ok = False

    try:
        qc = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
        qc.get_collections()
        qdrant_ok = True
    except Exception:
        qdrant_ok = False

    try:
        import requests

        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/tags"
        rsp = requests.get(url, timeout=3)
        ollama_ok = rsp.status_code == 200
    except Exception:
        ollama_ok = False

    return {
        "sql": sql_ok,
        "qdrant": qdrant_ok,
        "ollama": ollama_ok,
        "status": "ok" if (sql_ok and qdrant_ok and ollama_ok) else "degraded",
    }


@app.post("/api/chat")
def chat(request: ChatRequest):
    if pipeline is None:
        return err("Pipeline not ready", "PIPELINE_NOT_READY", status=503)

    def event_gen():
        try:
            for event in pipeline.stream(
                query=request.query,
                user_id=request.user_id,
                session_id=request.session_id,
                doc_scope=request.doc_scope,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.exception("Chat stream failed")
            payload = {"type": "error", "error": "Chat failed", "code": "CHAT_FAILED", "detail": str(e)}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/api/sessions/{user_id}")
def get_sessions(user_id: str):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT s.session_id, s.title, s.updated_at, COUNT(m.message_id) AS message_count
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON m.session_id = s.session_id
            WHERE s.user_id = ? AND s.status = 'active'
            GROUP BY s.session_id, s.title, s.updated_at
            ORDER BY s.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: str):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT role, content, cited_chunks, created_at FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["cited_chunks"] = json.loads(item.get("cited_chunks") or "[]")
            except Exception:
                item["cited_chunks"] = []
            items.append(item)
        return items
    finally:
        conn.close()


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE chat_sessions SET status = 'deleted' WHERE session_id = ?", (session_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/documents")
def get_documents():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT d.doc_id, d.doc_name, d.doc_type, d.total_pages, d.ingested_at,
                   COUNT(c.chunk_id) AS chunk_count
            FROM document_metadata d
            LEFT JOIN chunk_metadata c ON c.doc_id = d.doc_id
            WHERE d.status = 'active'
            GROUP BY d.doc_id, d.doc_name, d.doc_type, d.total_pages, d.ingested_at
            ORDER BY d.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/documents/upload")
def upload_document(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        return err("Only PDF uploads are supported", "INVALID_FILE_TYPE", status=400)

    data_dir = Path("app/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    dst = data_dir / file.filename
    content = file.file.read()
    dst.write_bytes(content)

    embedder = EmbedDocument()
    embedder.embed()

    return {
        "doc_id": str(uuid.uuid4()),
        "doc_name": file.filename,
        "total_pages": 0,
        "chunk_count": 0,
    }


@app.post("/api/documents/sync")
def sync_documents():
    try:
        embedder = EmbedDocument()
        summary = embedder.embed()
        return {"ok": True, "summary": summary}
    except Exception as e:
        return err("Failed to sync knowledge base", "DOCUMENT_SYNC_FAILED", str(e), 500)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT chunk_id FROM chunk_metadata WHERE doc_id = ?", (doc_id,)).fetchall()
        chunk_ids = [r["chunk_id"] for r in rows]

        qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
        collection = os.getenv("QDRANT_COLLECTION", "documents")
        from uuid import uuid5, NAMESPACE_URL

        points = [str(uuid5(NAMESPACE_URL, cid)) for cid in chunk_ids]
        if points:
            qdrant.delete(collection_name=collection, points_selector=points)

        conn.execute("UPDATE document_metadata SET status = 'deleted' WHERE doc_id = ?", (doc_id,))
        conn.commit()
        return {"ok": True}
    except Exception as e:
        return err("Failed to delete document", "DOCUMENT_DELETE_FAILED", str(e), 500)
    finally:
        conn.close()
