from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from rank_bm25 import BM25Okapi


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "db" / "sql_db.db"


@dataclass
class RetrievedChunk:
    chunk_id: str
    payload: dict[str, Any]
    dense_score: float
    bm25_score: float
    rrf_score: float


class HybridRetriever:
    def __init__(self) -> None:
        self._qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
        self._collection = os.getenv("QDRANT_COLLECTION", "documents")
        self._embedding = OllamaEmbeddings(
            model="nomic-embed-text",
            base_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        )
        self._db_path = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))

        self._bm25: BM25Okapi | None = None
        self._bm25_docs: list[dict[str, Any]] = []
        self._build_bm25_index()

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _build_bm25_index(self) -> None:
        docs: list[dict[str, Any]] = []
        if os.path.exists(self._db_path):
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                if self._table_exists(conn, "structured_chunks"):
                    rows = conn.execute(
                        "SELECT chunk_id, doc_id, doc_name, page_start, page_end, heading_h1, heading_h2, heading_h3, content FROM structured_chunks"
                    ).fetchall()
                    docs.extend(dict(r) for r in rows)
            finally:
                conn.close()

        if not docs:
            try:
                points, _ = self._qdrant.scroll(
                    collection_name=self._collection,
                    limit=5000,
                    with_payload=True,
                    with_vectors=False,
                )
                for p in points:
                    payload = p.payload or {}
                    text = payload.get("content")
                    if not text:
                        continue
                    docs.append(
                        {
                            "chunk_id": payload.get("chunk_id") or str(p.id),
                            "doc_id": payload.get("doc_id"),
                            "doc_name": payload.get("doc_name"),
                            "page_start": payload.get("page_start"),
                            "page_end": payload.get("page_end"),
                            "heading_h1": payload.get("heading_h1"),
                            "heading_h2": payload.get("heading_h2"),
                            "heading_h3": payload.get("heading_h3"),
                            "content": text,
                        }
                    )
            except Exception:
                docs = []

        self._bm25_docs = docs
        if docs:
            corpus = [str(d.get("content", "")).lower().split() for d in docs]
            self._bm25 = BM25Okapi(corpus)

    def _dense_search(self, query: str, top_k: int, doc_scope: str | None) -> list[dict[str, Any]]:
        query_vec = self._embedding.embed_query(f"search_query: {query}")
        q_filter = None
        if doc_scope:
            q_filter = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_scope))]
            )

        # qdrant-client API changed across versions:
        # older clients expose `.search`, newer ones expose `.query_points`.
        points = None
        try:
            if hasattr(self._qdrant, "search"):
                points = self._qdrant.search(
                    collection_name=self._collection,
                    query_vector=query_vec,
                    query_filter=q_filter,
                    limit=top_k,
                    with_payload=True,
                )
            else:
                response = self._qdrant.query_points(
                    collection_name=self._collection,
                    query=query_vec,
                    query_filter=q_filter,
                    limit=top_k,
                    with_payload=True,
                )
                points = getattr(response, "points", response)
        except Exception:
            # Qdrant can sporadically return internal errors (e.g. OutputTooSmall).
            # Degrade gracefully to sparse retrieval instead of failing the request.
            return []

        results: list[dict[str, Any]] = []
        for p in points:
            payload = p.payload or {}
            results.append(
                {
                    "chunk_id": payload.get("chunk_id") or str(p.id),
                    "payload": payload,
                    "dense_score": float(p.score),
                }
            )
        return results

    def _bm25_search(self, query: str, top_k: int, doc_scope: str | None) -> list[dict[str, Any]]:
        if not self._bm25 or not self._bm25_docs:
            return []

        scores = self._bm25.get_scores(query.lower().split())
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)

        results: list[dict[str, Any]] = []
        for idx, score in indexed:
            if len(results) >= top_k:
                break
            doc = self._bm25_docs[idx]
            if doc_scope and doc.get("doc_id") != doc_scope:
                continue
            payload = {
                "doc_id": doc.get("doc_id"),
                "doc_name": doc.get("doc_name"),
                "chunk_id": doc.get("chunk_id"),
                "chunk_type": "structured",
                "heading_h1": doc.get("heading_h1"),
                "heading_h2": doc.get("heading_h2"),
                "heading_h3": doc.get("heading_h3"),
                "page_start": doc.get("page_start"),
                "page_end": doc.get("page_end"),
                "content": doc.get("content"),
            }
            results.append(
                {
                    "chunk_id": doc.get("chunk_id"),
                    "payload": payload,
                    "bm25_score": float(score),
                }
            )
        return results

    def _rrf_merge(
        self,
        dense: list[dict[str, Any]],
        sparse: list[dict[str, Any]],
        top_k: int,
        k: int = 60,
    ) -> list[RetrievedChunk]:
        merged: dict[str, dict[str, Any]] = {}

        for rank, item in enumerate(dense, start=1):
            cid = item["chunk_id"]
            bucket = merged.setdefault(
                cid,
                {
                    "chunk_id": cid,
                    "payload": item["payload"],
                    "dense_score": 0.0,
                    "bm25_score": 0.0,
                    "rrf_score": 0.0,
                },
            )
            bucket["dense_score"] = item.get("dense_score", 0.0)
            bucket["rrf_score"] += 1.0 / (k + rank)

        for rank, item in enumerate(sparse, start=1):
            cid = item["chunk_id"]
            bucket = merged.setdefault(
                cid,
                {
                    "chunk_id": cid,
                    "payload": item["payload"],
                    "dense_score": 0.0,
                    "bm25_score": 0.0,
                    "rrf_score": 0.0,
                },
            )
            bucket["bm25_score"] = item.get("bm25_score", 0.0)
            bucket["rrf_score"] += 1.0 / (k + rank)

        ranked = sorted(merged.values(), key=lambda x: x["rrf_score"], reverse=True)[:top_k]
        return [RetrievedChunk(**item) for item in ranked]

    def retrieve(self, query: str, top_k: int = 12, doc_scope: str | None = None) -> list[RetrievedChunk]:
        try:
            dense = self._dense_search(query=query, top_k=top_k, doc_scope=doc_scope)
        except Exception:
            dense = []
        try:
            sparse = self._bm25_search(query=query, top_k=top_k, doc_scope=doc_scope)
        except Exception:
            sparse = []

        if not dense and not sparse:
            return []

        if not sparse:
            return [
                RetrievedChunk(
                    chunk_id=item["chunk_id"],
                    payload=item["payload"],
                    dense_score=item.get("dense_score", 0.0),
                    bm25_score=0.0,
                    rrf_score=item.get("dense_score", 0.0),
                )
                for item in dense
            ]

        return self._rrf_merge(dense=dense, sparse=sparse, top_k=top_k)
