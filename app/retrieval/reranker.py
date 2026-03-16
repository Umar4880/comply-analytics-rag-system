from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentence_transformers import CrossEncoder

from app.retrieval.retriever import RetrievedChunk


@dataclass
class RerankedChunk:
    chunk_id: str
    payload: dict[str, Any]
    score: float


class CrossEncoderReranker:
    def __init__(self) -> None:
        self._model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_n: int = 5,
    ) -> list[RerankedChunk]:
        if not chunks:
            return []

        pairs = []
        for item in chunks:
            content = str(item.payload.get("content", ""))
            pairs.append((query, content))

        scores = self._model.predict(pairs)
        ranked = sorted(
            [
                RerankedChunk(
                    chunk_id=item.chunk_id,
                    payload=item.payload,
                    score=float(score),
                )
                for item, score in zip(chunks, scores)
            ],
            key=lambda x: x.score,
            reverse=True,
        )
        return ranked[:top_n]
