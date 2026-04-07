from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.retrieval.reranker import RerankedChunk


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
        pass

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
            
            # For both structured and unstructured (tables), the payload's "content" 
            # now contains exactly what the LLM needs (text, or summary+table).
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
