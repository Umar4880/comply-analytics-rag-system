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


def _fetch_citation_details(chunk_ids: list[str]) -> list[dict[str, Any]]:
    if not chunk_ids:
        return []

    try:
        qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
        collection = os.getenv("QDRANT_COLLECTION", "documents")
        from uuid import uuid5, NAMESPACE_URL

        point_ids = [str(uuid5(NAMESPACE_URL, cid)) for cid in chunk_ids]
        points = qdrant.retrieve(collection_name=collection, ids=point_ids, with_payload=True, with_vectors=False)

        by_chunk: dict[str, dict[str, Any]] = {}
        for point in points:
            payload = point.payload or {}
            cid = str(payload.get("chunk_id", ""))
            if not cid:
                continue
            doc_name = str(payload.get("doc_name", "unknown"))
            page_start = int(payload.get("page_start", 1) or 1)
            page_end = int(payload.get("page_end", page_start) or page_start)
            h1 = str(payload.get("heading_h1", "") or "").strip()
            h2 = str(payload.get("heading_h2", "") or "").strip()
            h3 = str(payload.get("heading_h3", "") or "").strip()
            section = " > ".join(part for part in [h1, h2, h3] if part) or "N/A"
            by_chunk[cid] = {
                "chunk_id": cid,
                "doc_name": doc_name,
                "section": section,
                "page_start": page_start,
                "page_end": page_end,
                "label": f"{doc_name} (Pages {page_start}-{page_end})",
                "display": f"[{doc_name} section={section} pages={page_start}-{page_end} chunk_id={cid}]",
            }

        # Preserve incoming order.
        return [by_chunk[cid] for cid in chunk_ids if cid in by_chunk]
    except Exception:
        return []


def get_db_path() -> str:
    return os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))


def get_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    defaults = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.10.8:3000",
    ]
    merged: list[str] = []
    for origin in defaults + parsed:
        if origin not in merged:
            merged.append(origin)
    return merged


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
    allow_origins=get_allowed_origins(),
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?$",
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

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
            item["citation_details"] = _fetch_citation_details(item["cited_chunks"])
            items.append(item)
        return items
    finally:
        conn.close()


@app.get("/api/citations")
def get_citations(ids: str = ""):
    chunk_ids = [part.strip() for part in ids.split(",") if part.strip()]
    return _fetch_citation_details(chunk_ids)


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
    if not file.filename.lower().endswith((".pdf", ".docx")):
        return err("Only PDF and DOCX uploads are supported", "INVALID_FILE_TYPE", status=400)

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
