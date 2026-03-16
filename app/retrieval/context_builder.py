from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.retrieval.reranker import RerankedChunk


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "db" / "sql_db.db"


@dataclass
class EnrichedContext:
    chunk_id: str
    payload: dict[str, Any]
    llm_context: str


class ContextBuilder:
    def __init__(self) -> None:
        self._db_path = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))

    def _find_parent_chunk(self, doc_id: str, field_name: str, field_value: str) -> str | None:
        if not field_value or not os.path.exists(self._db_path):
            return None

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                f"SELECT content FROM structured_chunks WHERE doc_id = ? AND {field_name} = ? ORDER BY updated_at DESC LIMIT 1",
                (doc_id, field_value),
            ).fetchone()
            if row:
                return str(row["content"])
            return None
        except Exception:
            return None
        finally:
            conn.close()

    def _build_unstructured_context(self, payload: dict[str, Any]) -> str:
        doc_id = str(payload.get("doc_id", ""))
        h3 = str(payload.get("heading_h3", "") or "")
        h2 = str(payload.get("heading_h2", "") or "")
        h1 = str(payload.get("heading_h1", "") or "")

        parent = None
        if h3:
            parent = self._find_parent_chunk(doc_id, "heading_h3", h3)
        if not parent and h2:
            parent = self._find_parent_chunk(doc_id, "heading_h2", h2)
        if not parent and h1:
            parent = self._find_parent_chunk(doc_id, "heading_h1", h1)

        table_md = str(payload.get("content", ""))
        if parent:
            return f"{parent}\n\n{table_md}".strip()
        return table_md

    def build(self, chunks: list[RerankedChunk]) -> list[EnrichedContext]:
        contexts: list[EnrichedContext] = []
        for chunk in chunks:
            payload = chunk.payload
            chunk_type = str(payload.get("chunk_type", "structured"))
            if chunk_type == "unstructured":
                llm_context = self._build_unstructured_context(payload)
            else:
                llm_context = str(payload.get("content", ""))

            contexts.append(
                EnrichedContext(
                    chunk_id=chunk.chunk_id,
                    payload=payload,
                    llm_context=llm_context,
                )
            )
        return contexts
