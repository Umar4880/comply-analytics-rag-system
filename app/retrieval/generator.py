from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Any, Iterable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.retrieval.context_builder import EnrichedContext

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are a strictly grounded assistant. Answer ONLY using the provided context. "
    "Use clear section headings and concise bullets where helpful. "
    "If context includes tabular data and the question asks to list/compare entities, return a markdown table in the answer. "
    "Prefer markdown tables for country lists, comparisons, or mechanisms. "
    "Keep table columns concise and factually grounded in context. "
    "Cite sources for every claim using this exact format: "
    "[doc_name, Section <section_heading_if_available>, Pages X-Y]. "
    "Always include Pages X-Y from metadata as numeric page numbers. "
    "Do not treat heading numbers like 3.2.1 as page numbers. "
    "Never output raw internal identifiers like chunk ids. "
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
        self._model = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2:latest")
        self._last_model_used = "unknown"
        self._llm = ChatOllama(
            model=self._model,
            base_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            temperature=0.1,
        )

    def get_last_model_used(self) -> str:
        return self._last_model_used

    def generate_title(self, user_query: str, assistant_answer: str) -> str:
        messages = [
            SystemMessage(
                content=(
                    "Generate a short conversation title (max 7 words). "
                    "Return only the title text, no quotes, no punctuation at the end."
                )
            ),
            HumanMessage(
                content=(
                    f"User question: {user_query}\n"
                    f"Assistant answer: {assistant_answer[:500]}"
                )
            ),
        ]

        response = None
        try:
            response = self._llm.invoke(messages)
        except Exception:
            response = None

        if response is None:
            return "New Chat"

        if isinstance(response.content, str):
            title = response.content.strip()
        else:
            title = " ".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in response.content
            ).strip()

        title = " ".join(title.replace("\n", " ").replace('"', "").split())
        if not title:
            return "New Chat"
        return title[:80]

    def _format_context(self, contexts: list[EnrichedContext]) -> str:
        blocks = []
        for idx, ctx in enumerate(contexts, start=1):
            doc_name = ctx.doc_name or "unknown"
            page_start = ctx.page_start
            page_end = ctx.page_end
            section_parts = [ctx.heading_h1, ctx.heading_h2, ctx.heading_h3]
            section = " > ".join(part.strip() for part in section_parts if part and part.strip())
            if not section:
                section = "N/A"
            blocks.append(
                f"[Context {idx}] source={doc_name} section={section} pages={page_start}-{page_end}\n{ctx.llm_context}"
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

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        logger.info(
            "LLM invoke start | query=%s | context_count=%s | chunk_ids=%s",
            query,
            len(contexts),
            [ctx.chunk_id for ctx in contexts],
        )

        try:
            response = self._llm.invoke(messages)
            self._last_model_used = f"ollama:{self._model}"
        except Exception:
            logger.exception("LLM invoke failed")
            raise

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

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        def _yield_stream(stream_iter: Iterable[Any]) -> Iterable[str]:
            for chunk in stream_iter:
                content = getattr(chunk, "content", "")
                if isinstance(content, str):
                    if content:
                        yield content
                elif isinstance(content, list):
                    for part in content:
                        text = part.get("text", "") if isinstance(part, dict) else str(part)
                        if text:
                            yield text

        self._last_model_used = f"ollama:{self._model}"
        logger.info(
            "LLM stream start | model=%s | query=%s | context_count=%s",
            self._last_model_used,
            query,
            len(contexts),
        )
        try:
            for token in _yield_stream(self._llm.stream(messages)):
                yield token
        except Exception:
            logger.exception("LLM stream failed")
            raise