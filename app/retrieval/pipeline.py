from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, TypedDict
from uuid import uuid4

import redis
from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from app.retrieval.context_builder import ContextBuilder
from app.retrieval.generator import AnswerGenerator
from app.retrieval.guardrails import InputGuardrails
from app.retrieval.memory import ConversationMemory
from app.retrieval.reranker import CrossEncoderReranker
from app.retrieval.retriever import HybridRetriever
from app.retrieval.checkpointer import Checkpointer

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "db" / "sql_db.db"
logger = logging.getLogger(__name__)


class RetrievalPipeline:
    class _GraphState(TypedDict, total=False):
        query: str
        doc_scope: str | None
        guardrail_safe: bool
        guardrail_reason: str
        contexts: list[dict[str, Any]]
        confidence: float
        generated_answer: str
        generated_confidence: int
        cited_chunks: list[dict[str, Any]]
        execution_status: str
        attempt_count: int
        start_time: str
        error_message: str | None

    def __init__(self) -> None:
        self._db_path = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))

        self.guardrails = InputGuardrails()
        self.retriever = HybridRetriever()
        self.reranker = CrossEncoderReranker()
        self.context_builder = ContextBuilder()
        self.memory = ConversationMemory()
        self.generator = AnswerGenerator()
        self.checkpointer = Checkpointer(self._db_path)

        self._redis = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        self._fallback_cache: dict[str, str] = {}
        self._expander = ChatOllama(
            model=os.getenv("OLLAMA_CHAT_MODEL", "llama3.2:latest"),
            base_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            temperature=0.2,
        )
        self._retrieval_graph = self._build_retrieval_graph()

  #----------------------------utility methods--------------------------------#
    def _generate_session_id(self):
        return str(uuid4())
    
    def _citation_label_from_context(self, ctx: dict[str, Any]) -> str:
        doc_name = str(ctx.get("doc_name", "unknown"))
        page_start = int(ctx.get("page_start", 1) or 1)
        page_end = int(ctx.get("page_end", page_start) or page_start)
        h1 = str(ctx.get("heading_h1", "") or "").strip()
        h2 = str(ctx.get("heading_h2", "") or "").strip()
        h3 = str(ctx.get("heading_h3", "") or "").strip()
        section = " > ".join(part for part in [h1, h2, h3] if part) or "N/A"
        chunk_id = str(ctx.get("chunk_id", ""))
        return f"[{doc_name} section={section} pages={page_start}-{page_end} chunk_id={chunk_id}]"

    def _build_citation_details(self, contexts: list[dict[str, Any]]) -> list[dict[str, str | int]]:
        details: list[dict[str, str | int]] = []
        for ctx in contexts:
            doc_name = str(ctx.get("doc_name", "unknown"))
            page_start = int(ctx.get("page_start", 1) or 1)
            page_end = int(ctx.get("page_end", page_start) or page_start)
            h1 = str(ctx.get("heading_h1", "") or "").strip()
            h2 = str(ctx.get("heading_h2", "") or "").strip()
            h3 = str(ctx.get("heading_h3", "") or "").strip()
            section = " > ".join(part for part in [h1, h2, h3] if part) or "N/A"
            chunk_id = str(ctx.get("chunk_id", ""))
            details.append(
                {
                    "chunk_id": chunk_id,
                    "doc_name": doc_name,
                    "section": section,
                    "page_start": page_start,
                    "page_end": page_end,
                    "label": f"{doc_name} (Pages {page_start}-{page_end})",
                    "display": f"[{doc_name} section={section} pages={page_start}-{page_end} chunk_id={chunk_id}]",
                }
            )
        return details

    def _get_session_title(self, session_id: str) -> str:
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute("SELECT title FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row and row[0]:
                return str(row[0])
            return "New Chat"
        finally:
            conn.close()

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

    def _ensure_session(self, user_id: str, session_id: str | None, query: str) -> tuple[str, bool]:
        sid = session_id or str(uuid.uuid4())
        created = False
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute("SELECT session_id FROM chat_sessions WHERE session_id = ?", (sid,)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO chat_sessions(session_id, user_id, title, created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
                    (sid, user_id, "New Chat", self._now(), self._now()),
                )
                conn.commit()
                created = True
        finally:
            conn.close()
        return sid, created

    def _maybe_generate_session_title(self, session_id: str, query: str, answer: str) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute("SELECT title FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
            current = str(row[0]) if row and row[0] is not None else ""
            if current and current != "New Chat":
                return

            title = self.generator.generate_title(user_query=query, assistant_answer=answer)
            if not title:
                title = "New Chat"
            conn.execute(
                "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                (title[:80], self._now(), session_id),
            )
            conn.commit()
            logger.info("Session title generated | session_id=%s | title=%s", session_id, title[:80])
        except Exception:
            logger.exception("Failed to generate session title | session_id=%s", session_id)
        finally:
            conn.close()

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
        rsp = None
        try:
            rsp = self._expander.invoke([HumanMessage(content=prompt)])
        except Exception:
            rsp = None

        if rsp is None:
            return [f"{query} details", f"{query} overview", f"{query} steps"]

        if isinstance(rsp.content, str):
            text = rsp.content
        else:
            text = "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in rsp.content
            )
        items = [line.strip("- •\t ") for line in text.splitlines() if line.strip()]
        return items[:3]

    def _retrieve_context(self, query: str, doc_scope: str | None, top_k: int, top_n: int,) -> tuple[list[dict[str, Any]], float]:
        try:
            t0 = time.perf_counter()
            retrieved = self.retriever.retrieve(query=query, top_k=top_k, doc_scope=doc_scope)
            t1 = time.perf_counter()
            logger.info(
                "Retrieve complete | query=%s | doc_scope=%s | retrieved=%s",
                query,
                doc_scope,
                len(retrieved),
            )
            reranked = self.reranker.rerank(query=query, chunks=retrieved, top_n=top_n)
            t2 = time.perf_counter()
            contexts = self.context_builder.build(reranked)
            t3 = time.perf_counter()
            logger.info(
                "Context build | query=%s | chunk_ids=%s | docs=%s | retrieve_ms=%s | rerank_ms=%s | context_ms=%s",
                query,
                [c.chunk_id for c in contexts],
                [str(c.payload.get("doc_name", "unknown")) for c in contexts],
                round((t1 - t0) * 1000, 1),
                round((t2 - t1) * 1000, 1),
                round((t3 - t2) * 1000, 1),
            )
            confidence = sum(item.score for item in reranked) / max(1, len(reranked))
            return [asdict(c) for c in contexts], float(confidence)
        except Exception:
            logger.exception("Retrieve context failed | query=%s | doc_scope=%s", query, doc_scope)
            return [], 0.0
    
    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
    
# --------------------------------Main implementation--------------------------------#

    def _build_retrieval_graph(self):
        graph = StateGraph(self._GraphState)

        graph.add_node("guardrails", self._graph_guardrails)
        graph.add_node("retrieve", self._graph_retrieve)
        
        graph.set_entry_point("guardrails")
        graph.add_edge("guardrails", "retrieve")
        graph.add_edge("retrieve", END)

        checkpointer = self.checkpointer.get_checkpointer()
        return graph.compile(checkpointer=checkpointer)

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
            top_k=12,
            top_n=5
        )

        if confidence < 0.3:
            expanded = self._expand_query(state["query"])
            merged = contexts[:]
            for alt in expanded:
                ctx, _ = self._retrieve_context(query=alt, doc_scope=state.get("doc_scope"), top_k=12, top_n=5)
                merged.extend(ctx)
            uniq: dict[str, dict[str, Any]] = {}
            for item in merged:
                uniq[item["chunk_id"]] = item
            contexts = list(uniq.values())[:8]

        return {"contexts": contexts, "confidence": float(confidence)}
    
    def _graph_generate(self, state: _GraphState,
        query: str,
        user_id: str,
        session_id: str | None = None,
        doc_scope: str | None = None,
        ) :
        logger.info("Stream start | query=%s | user_id=%s | doc_scope=%s", query, user_id, doc_scope)

        config = {"configurable": {"session_id": session_id}}

        gate = self.guardrails.validate(query)
        if not gate.safe:
            yield {
                "type": "error",
                "error": gate.reason or "Query blocked by guardrails",
                "code": "GUARDRAIL_BLOCKED",
                "detail": None,
            }
            return
        
        sid, is_new_session = self._ensure_session(user_id=user_id, session_id=session_id, query=query)

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
        citation_details = self._build_citation_details(contexts)

        self._store_message(sid, "user", query)
        self._store_message(sid, "assistant", answer, cited_chunks)
        if is_new_session:
            self._maybe_generate_session_title(sid, query, answer)


    def ask(
        self,
        query: str,
        user_id: str,
        session_id: str | None = None,
        doc_scope: str | None = None,
    ) -> dict[str, Any]:
        logger.info("Ask start | query=%s | user_id=%s | doc_scope=%s", query, user_id, doc_scope)

        gate = self.guardrails.validate(query)
        if not gate.safe:
            return {
                "error": gate.reason or "Query blocked by guardrails",
                "code": "GUARDRAIL_BLOCKED",
                "detail": None,
            }

        key = self._cache_key(query, doc_scope)
        cached = self._cache_get(key)
        sid, is_new_session = self._ensure_session(user_id=user_id, session_id=session_id, query=query)

        if cached:
            self._store_message(sid, "user", query)
            self._store_message(sid, "assistant", cached["answer"], cached.get("cited_chunks", []))
            if is_new_session:
                self._maybe_generate_session_title(sid, query, cached.get("answer", ""))
            return {
                **cached,
                "session_id": sid,
                "session_title": self._get_session_title(sid),
                "from_cache": True,
            }
        
        state = self._retrieval_graph.invoke({"query": query, "doc_scope": doc_scope})

        contexts = state.get("contexts", [])
        confidence = float(state.get("confidence", 0.0))

        history = self.memory.load_history(sid)
        from app.retrieval.context_builder import EnrichedContext

        enriched = [EnrichedContext(**c) for c in contexts]
        gen = self.generator.generate(query=query, contexts=enriched, history=history)

        self._store_message(sid, "user", query)
        self._store_message(sid, "assistant", gen.answer, gen.cited_chunks)
        if is_new_session:
            self._maybe_generate_session_title(sid, query, gen.answer)

        response = {
            "answer": gen.answer,
            "cited_chunks": gen.cited_chunks,
            "citation_details": self._build_citation_details(contexts),
            "confidence": gen.confidence,
            "tokens_used": gen.tokens_used,
            "model_used": self.generator.get_last_model_used(),
            "session_id": sid,
            "session_title": self._get_session_title(sid),
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
        
        
        final = {
            "answer": answer,
            "cited_chunks": cited_chunks,
            "citation_details": citation_details,
            "session_id": sid,
            "session_title": self._get_session_title(sid),
            "confidence": max(0.1, min(0.95, 0.45 + (0.1 * min(len(enriched), 5)))),
            "model_used": self.generator.get_last_model_used(),
            "from_cache": False,
        }

        yield {"type": "final", **{k: v for k, v in final.items() if k != "answer"}}

        


