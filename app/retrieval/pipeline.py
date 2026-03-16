from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, TypedDict

import redis
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from app.retrieval.context_builder import ContextBuilder
from app.retrieval.generator import AnswerGenerator
from app.retrieval.guardrails import InputGuardrails
from app.retrieval.memory import ConversationMemory
from app.retrieval.reranker import CrossEncoderReranker
from app.retrieval.retriever import HybridRetriever

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "db" / "sql_db.db"


class RetrievalPipeline:
    class _GraphState(TypedDict, total=False):
        query: str
        doc_scope: str | None
        guardrail_safe: bool
        guardrail_reason: str
        contexts: list[dict[str, Any]]
        confidence: float

    def __init__(self) -> None:
        self.guardrails = InputGuardrails()
        self.retriever = HybridRetriever()
        self.reranker = CrossEncoderReranker()
        self.context_builder = ContextBuilder()
        self.memory = ConversationMemory()
        self.generator = AnswerGenerator()

        self._db_path = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))
        self._redis = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        self._fallback_cache: dict[str, str] = {}
        self._expander = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            temperature=0.2,
        )
        self._retrieval_graph = self._build_retrieval_graph()

    def _build_retrieval_graph(self):
        graph = StateGraph(self._GraphState)
        graph.add_node("guardrails", self._graph_guardrails)
        graph.add_node("retrieve", self._graph_retrieve)
        graph.set_entry_point("guardrails")
        graph.add_edge("guardrails", "retrieve")
        graph.add_edge("retrieve", END)
        return graph.compile()

    def _graph_guardrails(self, state: _GraphState) -> _GraphState:
        gate = self.guardrails.validate(state["query"])
        return {
            "guardrail_safe": gate.safe,
            "guardrail_reason": gate.reason,
        }

    def _graph_retrieve(self, state: _GraphState) -> _GraphState:
        if not state.get("guardrail_safe", True):
            return {"contexts": [], "confidence": 0.0}

        contexts, confidence = self._retrieve_context(
            query=state["query"],
            doc_scope=state.get("doc_scope"),
        )

        if confidence < 0.3:
            expanded = self._expand_query(state["query"])
            merged = contexts[:]
            for alt in expanded:
                ctx, _ = self._retrieve_context(query=alt, doc_scope=state.get("doc_scope"))
                merged.extend(ctx)
            uniq: dict[str, dict[str, Any]] = {}
            for item in merged:
                uniq[item["chunk_id"]] = item
            contexts = list(uniq.values())[:8]

        return {"contexts": contexts, "confidence": float(confidence)}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _cache_key(self, query: str, doc_scope: str | None) -> str:
        raw = f"{query}::{doc_scope or 'all'}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            value = self._redis.get(key)
        except Exception:
            value = self._fallback_cache.get(key)
        if not value:
            return None
        try:
            return json.loads(value)
        except Exception:
            return None

    def _cache_set(self, key: str, value: dict[str, Any]) -> None:
        raw = json.dumps(value)
        try:
            self._redis.setex(key, 3600, raw)
        except Exception:
            self._fallback_cache[key] = raw

    def _ensure_session(self, user_id: str, session_id: str | None, query: str) -> str:
        sid = session_id or str(uuid.uuid4())
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute("SELECT session_id FROM chat_sessions WHERE session_id = ?", (sid,)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO chat_sessions(session_id, user_id, title, created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
                    (sid, user_id, query[:80], self._now(), self._now()),
                )
                conn.commit()
        finally:
            conn.close()
        return sid

    def _store_message(self, session_id: str, role: str, content: str, cited_chunks: list[str] | None = None) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT INTO chat_messages(message_id, session_id, role, content, cited_chunks, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), session_id, role, content, json.dumps(cited_chunks or []), self._now()),
            )
            conn.execute("UPDATE chat_sessions SET updated_at=? WHERE session_id=?", (self._now(), session_id))
            conn.commit()
        finally:
            conn.close()

    def _expand_query(self, query: str) -> list[str]:
        prompt = (
            "Generate 3 concise alternative phrasings for the search query. "
            "Return one query per line and nothing else. Query: " + query
        )
        try:
            rsp = self._expander.invoke([HumanMessage(content=prompt)])
            if isinstance(rsp.content, str):
                text = rsp.content
            else:
                text = "\n".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in rsp.content
                )
            items = [line.strip("- •\t ") for line in text.splitlines() if line.strip()]
            return items[:3]
        except Exception:
            return [f"{query} details", f"{query} overview", f"{query} steps"]

    def _retrieve_context(self, query: str, doc_scope: str | None) -> tuple[list[dict[str, Any]], float]:
        retrieved = self.retriever.retrieve(query=query, top_k=12, doc_scope=doc_scope)
        reranked = self.reranker.rerank(query=query, chunks=retrieved, top_n=5)
        contexts = self.context_builder.build(reranked)
        confidence = sum(item.score for item in reranked) / max(1, len(reranked))
        return [asdict(c) for c in contexts], float(confidence)

    def ask(
        self,
        query: str,
        user_id: str,
        session_id: str | None = None,
        doc_scope: str | None = None,
    ) -> dict[str, Any]:
        state = self._retrieval_graph.invoke({"query": query, "doc_scope": doc_scope})
        if not state.get("guardrail_safe", True):
            return {
                "error": state.get("guardrail_reason", "Query blocked by guardrails"),
                "code": "GUARDRAIL_BLOCKED",
                "detail": None,
            }

        key = self._cache_key(query, doc_scope)
        cached = self._cache_get(key)
        sid = self._ensure_session(user_id=user_id, session_id=session_id, query=query)

        if cached:
            self._store_message(sid, "user", query)
            self._store_message(sid, "assistant", cached["answer"], cached.get("cited_chunks", []))
            return {
                **cached,
                "session_id": sid,
                "from_cache": True,
            }

        contexts = state.get("contexts", [])
        confidence = float(state.get("confidence", 0.0))

        history = self.memory.load_history(sid)
        from app.retrieval.context_builder import EnrichedContext

        enriched = [EnrichedContext(**c) for c in contexts]
        gen = self.generator.generate(query=query, contexts=enriched, history=history)

        self._store_message(sid, "user", query)
        self._store_message(sid, "assistant", gen.answer, gen.cited_chunks)

        response = {
            "answer": gen.answer,
            "cited_chunks": gen.cited_chunks,
            "confidence": gen.confidence,
            "tokens_used": gen.tokens_used,
            "session_id": sid,
            "from_cache": False,
        }
        self._cache_set(key, response)
        return response

    def stream(
        self,
        query: str,
        user_id: str,
        session_id: str | None = None,
        doc_scope: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        state = self._retrieval_graph.invoke({"query": query, "doc_scope": doc_scope})
        if not state.get("guardrail_safe", True):
            yield {
                "type": "error",
                "error": state.get("guardrail_reason", "Query blocked by guardrails"),
                "code": "GUARDRAIL_BLOCKED",
                "detail": None,
            }
            return

        key = self._cache_key(query, doc_scope)
        cached = self._cache_get(key)
        sid = self._ensure_session(user_id=user_id, session_id=session_id, query=query)

        if cached:
            yield {"type": "token", "token": cached["answer"]}
            yield {
                "type": "final",
                "cited_chunks": cached.get("cited_chunks", []),
                "session_id": sid,
                "confidence": cached.get("confidence", 0.0),
                "from_cache": True,
            }
            self._store_message(sid, "user", query)
            self._store_message(sid, "assistant", cached["answer"], cached.get("cited_chunks", []))
            return

        contexts = state.get("contexts", [])

        history = self.memory.load_history(sid)
        from app.retrieval.context_builder import EnrichedContext

        enriched = [EnrichedContext(**c) for c in contexts]

        tokens: list[str] = []
        for token in self.generator.stream_generate(query=query, contexts=enriched, history=history):
            tokens.append(token)
            yield {"type": "token", "token": token}

        answer = "".join(tokens)
        cited_chunks = [ctx.chunk_id for ctx in enriched]
        final = {
            "answer": answer,
            "cited_chunks": cited_chunks,
            "session_id": sid,
            "confidence": max(0.1, min(0.95, 0.45 + (0.1 * min(len(enriched), 5)))),
            "from_cache": False,
        }

        self._store_message(sid, "user", query)
        self._store_message(sid, "assistant", answer, cited_chunks)
        self._cache_set(key, final)

        yield {"type": "final", **{k: v for k, v in final.items() if k != "answer"}}
