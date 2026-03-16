from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.retrieval.context_builder import EnrichedContext


SYSTEM_PROMPT = (
    "You are a strictly grounded assistant. Answer ONLY using the provided context. "
    "Cite sources as [doc_name, Pages X-Y] for every claim. "
    "If context lacks the answer, respond exactly: "
    "'I do not have enough information in the provided documents to answer this question.' "
    "Never make up information."
)


@dataclass
class GenerationResult:
    answer: str
    cited_chunks: list[str]
    confidence: float
    tokens_used: int


class AnswerGenerator:
    def __init__(self) -> None:
        self._model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self._llm = ChatGoogleGenerativeAI(
            model=self._model,
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            temperature=0.1,
        )

    def _format_context(self, contexts: list[EnrichedContext]) -> str:
        blocks = []
        for idx, ctx in enumerate(contexts, start=1):
            p = ctx.payload
            doc_name = p.get("doc_name", "unknown")
            page_start = p.get("page_start", "?")
            page_end = p.get("page_end", "?")
            blocks.append(
                f"[Context {idx}] source={doc_name} pages={page_start}-{page_end} chunk_id={ctx.chunk_id}\n{ctx.llm_context}"
            )
        return "\n\n".join(blocks)

    def _confidence_from_context(self, contexts: list[EnrichedContext]) -> float:
        if not contexts:
            return 0.0
        return min(0.95, 0.45 + (0.1 * min(len(contexts), 5)))

    def generate(
        self,
        query: str,
        contexts: list[EnrichedContext],
        history: list[dict[str, Any]],
    ) -> GenerationResult:
        context_text = self._format_context(contexts)
        history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
        user_prompt = (
            f"Conversation history:\n{history_text}\n\n"
            f"Context:\n{context_text}\n\n"
            f"Question: {query}"
        )

        response = self._llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )

        if isinstance(response.content, str):
            answer = response.content
        else:
            answer = "".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in response.content
            )

        cited_chunks = [ctx.chunk_id for ctx in contexts]
        usage = getattr(response, "usage_metadata", {}) or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        tokens_used = input_tokens + output_tokens

        return GenerationResult(
            answer=answer,
            cited_chunks=cited_chunks,
            confidence=self._confidence_from_context(contexts),
            tokens_used=tokens_used,
        )

    def stream_generate(
        self,
        query: str,
        contexts: list[EnrichedContext],
        history: list[dict[str, Any]],
    ) -> Iterable[str]:
        context_text = self._format_context(contexts)
        history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
        user_prompt = (
            f"Conversation history:\n{history_text}\n\n"
            f"Context:\n{context_text}\n\n"
            f"Question: {query}"
        )

        for chunk in self._llm.stream(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        ):
            content = getattr(chunk, "content", "")
            if isinstance(content, str):
                if content:
                    yield content
            elif isinstance(content, list):
                for part in content:
                    text = part.get("text", "") if isinstance(part, dict) else str(part)
                    if text:
                        yield text
