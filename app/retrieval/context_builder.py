from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.database.sql import Database
from app.retrieval.reranker import RerankedChunk


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "db" / "sql_db.db"


@dataclass
class EnrichedContext:
    chunk_id: str
    payload: dict[str, Any]
    llm_context: str
    doc_name: str
    page_start: int
    page_end: int
    heading_h1: str
    heading_h2: str
    heading_h3: str
    chunk_type: str
    has_parent: bool


class ContextBuilder:
    def __init__(self) -> None:
        self._db_path = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))
        self._db = Database(db_path=self._db_path)

    def _find_parent_chunk(self, doc_id: str, field_name: str, field_value: str) -> dict[str, Any] | None:
        if not field_value or not os.path.exists(self._db_path):
            return None
        try:
            return self._db.find_parent_chunk(doc_id, field_name, field_value)
        except Exception:
            return None

    def _build_unstructured_context(self, payload: dict[str, Any]) -> tuple[str, bool]:
        doc_id = str(payload.get("doc_id", ""))
        h3 = str(payload.get("heading_h3", "") or "")
        h2 = str(payload.get("heading_h2", "") or "")
        h1 = str(payload.get("heading_h1", "") or "")

        table_md = str(payload.get("content", ""))
        context_hint = str(payload.get("context", "") or "")

        # If no heading metadata exists, use parser-captured context if available.
        if not h1 and not h2 and not h3:
            if context_hint:
                return f"{context_hint}\n\n{table_md}".strip(), False
            return table_md, False

        parent = None
        if h3:
            parent = self._find_parent_chunk(doc_id, "heading_h3", h3)
        if not parent and h2:
            parent = self._find_parent_chunk(doc_id, "heading_h2", h2)
        if not parent and h1:
            parent = self._find_parent_chunk(doc_id, "heading_h1", h1)

        if parent:
            return f"{str(parent.get('content', ''))}\n\n{table_md}".strip(), True
        return table_md, False

    def _dedupe_chunks(self, chunks: list[RerankedChunk]) -> list[RerankedChunk]:
        best_by_chunk_id: dict[str, RerankedChunk] = {}
        for chunk in chunks:
            current = best_by_chunk_id.get(chunk.chunk_id)
            if current is None or chunk.score > current.score:
                best_by_chunk_id[chunk.chunk_id] = chunk
        return list(best_by_chunk_id.values())

    def build(self, chunks: list[RerankedChunk]) -> list[EnrichedContext]:
        contexts: list[EnrichedContext] = []
        for chunk in self._dedupe_chunks(chunks):
            payload = chunk.payload
            chunk_type = str(payload.get("chunk_type", "structured"))
            if chunk_type == "unstructured":
                llm_context, has_parent = self._build_unstructured_context(payload)
            else:
                llm_context = str(payload.get("content", ""))
                has_parent = False

            page_start = int(payload.get("page_start", 1) or 1)
            page_end = int(payload.get("page_end", page_start) or page_start)

            contexts.append(
                EnrichedContext(
                    chunk_id=chunk.chunk_id,
                    payload=payload,
                    llm_context=llm_context,
                    doc_name=str(payload.get("doc_name", "unknown")),
                    page_start=page_start,
                    page_end=page_end,
                    heading_h1=str(payload.get("heading_h1", "") or ""),
                    heading_h2=str(payload.get("heading_h2", "") or ""),
                    heading_h3=str(payload.get("heading_h3", "") or ""),
                    chunk_type=chunk_type,
                    has_parent=has_parent,
                )
            )
        return contexts
