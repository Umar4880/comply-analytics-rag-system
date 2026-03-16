from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage, SystemMessage
except Exception:  # pragma: no cover
    ChatGoogleGenerativeAI = None
    HumanMessage = None
    SystemMessage = None


NO_INFO_ANSWER = "I do not have enough information in the provided documents to answer this question."
TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


@dataclass
class EvalRow:
    case_id: str
    question: str
    answer: str
    reference_answer: str
    cited_chunks: list[str]
    correctness_score: float
    faithfulness_score: float
    hallucinated: bool
    retrieval_hit_at_k: float | None
    retrieval_precision: float | None
    retrieval_recall: float | None
    error: str | None


def norm_tokens(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def token_f1(pred: str, gold: str) -> float:
    p = norm_tokens(pred)
    g = norm_tokens(gold)
    if not p or not g:
        return 0.0
    p_counts: dict[str, int] = {}
    g_counts: dict[str, int] = {}
    for t in p:
        p_counts[t] = p_counts.get(t, 0) + 1
    for t in g:
        g_counts[t] = g_counts.get(t, 0) + 1

    overlap = 0
    for t, c in p_counts.items():
        if t in g_counts:
            overlap += min(c, g_counts[t])

    precision = overlap / max(1, len(p))
    recall = overlap / max(1, len(g))
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def overlap_support_score(answer: str, evidence_text: str) -> float:
    ans = set(norm_tokens(answer))
    ev = set(norm_tokens(evidence_text))
    if not ans:
        return 0.0
    return len(ans & ev) / max(1, len(ans))


class LLMJudge:
    def __init__(self, model: str, api_key: str) -> None:
        self.available = bool(ChatGoogleGenerativeAI and HumanMessage and SystemMessage and api_key)
        if not self.available:
            self._llm = None
            return
        self._llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.0)

    def _invoke_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        if not self._llm:
            return None
        try:
            rsp = self._llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])
            text = rsp.content if isinstance(rsp.content, str) else "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in rsp.content
            )
            text = text.strip()
            if text.startswith("```"):
                text = text.strip("`")
                text = text.replace("json", "", 1).strip()
            return json.loads(text)
        except Exception:
            return None

    def score_correctness(self, question: str, answer: str, reference_answer: str) -> float:
        payload = self._invoke_json(
            system_prompt=(
                "You evaluate answer correctness. Return strict JSON: "
                '{"score": number between 0 and 1}. No extra keys.'
            ),
            user_prompt=(
                f"Question:\n{question}\n\nReference Answer:\n{reference_answer}\n\n"
                f"Model Answer:\n{answer}\n\n"
                "Score semantic correctness where 1.0 means fully correct and 0.0 means wrong."
            ),
        )
        if not payload:
            return 0.0
        try:
            return max(0.0, min(1.0, float(payload.get("score", 0.0))))
        except Exception:
            return 0.0

    def score_faithfulness(self, question: str, answer: str, evidence_text: str) -> tuple[float, bool]:
        payload = self._invoke_json(
            system_prompt=(
                "You evaluate if an answer is grounded in provided evidence. Return strict JSON: "
                '{"score": number between 0 and 1, "hallucinated": true|false}. No extra keys.'
            ),
            user_prompt=(
                f"Question:\n{question}\n\nEvidence:\n{evidence_text[:12000]}\n\n"
                f"Answer:\n{answer}\n\n"
                "If answer includes unsupported claims, set hallucinated=true and lower score."
            ),
        )
        if not payload:
            return 0.0, True
        try:
            score = max(0.0, min(1.0, float(payload.get("score", 0.0))))
            hallucinated = bool(payload.get("hallucinated", score < 0.5))
            return score, hallucinated
        except Exception:
            return 0.0, True


def parse_sse_chat(
    base_url: str,
    question: str,
    user_id: str,
    session_id: str | None,
    doc_scope: str | None,
    timeout_sec: int,
) -> tuple[str, dict[str, Any], str | None]:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "query": question,
        "user_id": user_id,
        "session_id": session_id,
        "doc_scope": doc_scope,
    }
    tokens: list[str] = []
    final_payload: dict[str, Any] = {}
    error_msg = None

    with requests.post(url, json=payload, stream=True, timeout=timeout_sec) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data_str = raw[len("data:") :].strip()
            if not data_str:
                continue
            event = json.loads(data_str)
            et = event.get("type")
            if et == "token":
                tokens.append(str(event.get("token", "")))
            elif et == "final":
                final_payload = event
            elif et == "error":
                error_msg = str(event.get("detail") or event.get("error") or "Chat failed")

    return "".join(tokens).strip(), final_payload, error_msg


def chunk_ids_to_evidence(chunk_ids: list[str], qdrant: QdrantClient, collection: str) -> str:
    if not chunk_ids:
        return ""

    point_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, cid)) for cid in chunk_ids]
    blocks: list[str] = []

    try:
        points = qdrant.retrieve(
            collection_name=collection,
            ids=point_ids,
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        points = []

    found_chunk_ids = set()
    for p in points:
        payload = p.payload or {}
        chunk_id = str(payload.get("chunk_id", ""))
        if chunk_id:
            found_chunk_ids.add(chunk_id)
        content = str(payload.get("content", ""))
        doc_name = str(payload.get("doc_name", "unknown"))
        page_start = payload.get("page_start", "?")
        page_end = payload.get("page_end", "?")
        blocks.append(f"[{doc_name} pages {page_start}-{page_end}]\n{content}")

    missing = [cid for cid in chunk_ids if cid not in found_chunk_ids]
    for cid in missing:
        try:
            points2, _ = qdrant.scroll(
                collection_name=collection,
                with_payload=True,
                with_vectors=False,
                limit=2,
                scroll_filter=Filter(must=[FieldCondition(key="chunk_id", match=MatchValue(value=cid))]),
            )
            for p in points2:
                payload = p.payload or {}
                content = str(payload.get("content", ""))
                doc_name = str(payload.get("doc_name", "unknown"))
                page_start = payload.get("page_start", "?")
                page_end = payload.get("page_end", "?")
                blocks.append(f"[{doc_name} pages {page_start}-{page_end}]\n{content}")
        except Exception:
            continue

    return "\n\n".join(blocks)


def load_benchmark(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Benchmark file must be a JSON array")
    return data


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    benchmark = load_benchmark(Path(args.benchmark))

    judge = LLMJudge(model=args.judge_model, api_key=os.getenv("GOOGLE_API_KEY", ""))
    use_llm_judge = bool(args.use_llm_judge and judge.available)

    qdrant = QdrantClient(url=args.qdrant_url)
    rows: list[EvalRow] = []

    for i, case in enumerate(benchmark, start=1):
        case_id = str(case.get("id") or f"case_{i}")
        question = str(case.get("question", "")).strip()
        reference_answer = str(case.get("reference_answer", "")).strip()
        doc_scope = case.get("doc_scope")
        expected_chunk_ids = [str(x) for x in case.get("expected_chunk_ids", [])]

        if not question:
            rows.append(
                EvalRow(
                    case_id=case_id,
                    question="",
                    answer="",
                    reference_answer=reference_answer,
                    cited_chunks=[],
                    correctness_score=0.0,
                    faithfulness_score=0.0,
                    hallucinated=True,
                    retrieval_hit_at_k=None,
                    retrieval_precision=None,
                    retrieval_recall=None,
                    error="Missing question in benchmark row",
                )
            )
            continue

        try:
            answer, final_payload, err = parse_sse_chat(
                base_url=args.api_base_url,
                question=question,
                user_id=args.user_id,
                session_id=None,
                doc_scope=doc_scope,
                timeout_sec=args.timeout_sec,
            )
        except Exception as e:
            rows.append(
                EvalRow(
                    case_id=case_id,
                    question=question,
                    answer="",
                    reference_answer=reference_answer,
                    cited_chunks=[],
                    correctness_score=0.0,
                    faithfulness_score=0.0,
                    hallucinated=True,
                    retrieval_hit_at_k=None,
                    retrieval_precision=None,
                    retrieval_recall=None,
                    error=f"Request failed: {e}",
                )
            )
            continue

        cited_chunks = [str(x) for x in final_payload.get("cited_chunks", [])]
        err_msg = err

        retrieval_hit = None
        retrieval_precision = None
        retrieval_recall = None
        if expected_chunk_ids:
            inter = set(expected_chunk_ids) & set(cited_chunks)
            retrieval_hit = 1.0 if inter else 0.0
            retrieval_precision = len(inter) / max(1, len(cited_chunks))
            retrieval_recall = len(inter) / max(1, len(expected_chunk_ids))

        evidence_text = chunk_ids_to_evidence(cited_chunks, qdrant=qdrant, collection=args.qdrant_collection)

        if reference_answer:
            if use_llm_judge:
                correctness = judge.score_correctness(question, answer, reference_answer)
            else:
                correctness = token_f1(answer, reference_answer)
        else:
            correctness = 0.0

        if use_llm_judge and evidence_text:
            faithfulness, hallucinated = judge.score_faithfulness(question, answer, evidence_text)
        else:
            support = overlap_support_score(answer, evidence_text)
            no_info_expected = bool(case.get("expect_no_answer", False))
            if no_info_expected:
                hallucinated = answer.strip() != NO_INFO_ANSWER
                faithfulness = 1.0 if not hallucinated else 0.0
            else:
                faithfulness = support
                hallucinated = support < args.heuristic_support_threshold

        rows.append(
            EvalRow(
                case_id=case_id,
                question=question,
                answer=answer,
                reference_answer=reference_answer,
                cited_chunks=cited_chunks,
                correctness_score=correctness,
                faithfulness_score=faithfulness,
                hallucinated=hallucinated,
                retrieval_hit_at_k=retrieval_hit,
                retrieval_precision=retrieval_precision,
                retrieval_recall=retrieval_recall,
                error=err_msg,
            )
        )

    def mean_safe(items: list[float]) -> float:
        return statistics.mean(items) if items else 0.0

    correctness_vals = [r.correctness_score for r in rows if not r.error]
    faithfulness_vals = [r.faithfulness_score for r in rows if not r.error]
    hallucination_rate = mean_safe([1.0 if r.hallucinated else 0.0 for r in rows if not r.error])

    hit_vals = [r.retrieval_hit_at_k for r in rows if r.retrieval_hit_at_k is not None]
    precision_vals = [r.retrieval_precision for r in rows if r.retrieval_precision is not None]
    recall_vals = [r.retrieval_recall for r in rows if r.retrieval_recall is not None]

    summary = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "cases_total": len(rows),
        "cases_success": len([r for r in rows if not r.error]),
        "cases_failed": len([r for r in rows if r.error]),
        "avg_correctness": mean_safe(correctness_vals),
        "avg_faithfulness": mean_safe(faithfulness_vals),
        "hallucination_rate": hallucination_rate,
        "avg_retrieval_hit_at_k": mean_safe([float(v) for v in hit_vals]),
        "avg_retrieval_precision": mean_safe([float(v) for v in precision_vals]),
        "avg_retrieval_recall": mean_safe([float(v) for v in recall_vals]),
        "llm_judge_used": use_llm_judge,
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"rag_eval_{stamp}.json"
    csv_path = out_dir / f"rag_eval_{stamp}.csv"

    json_payload = {
        "summary": summary,
        "rows": [
            {
                "id": r.case_id,
                "question": r.question,
                "answer": r.answer,
                "reference_answer": r.reference_answer,
                "cited_chunks": r.cited_chunks,
                "correctness_score": r.correctness_score,
                "faithfulness_score": r.faithfulness_score,
                "hallucinated": r.hallucinated,
                "retrieval_hit_at_k": r.retrieval_hit_at_k,
                "retrieval_precision": r.retrieval_precision,
                "retrieval_recall": r.retrieval_recall,
                "error": r.error,
            }
            for r in rows
        ],
    }
    json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "question",
                "answer",
                "reference_answer",
                "cited_chunks",
                "correctness_score",
                "faithfulness_score",
                "hallucinated",
                "retrieval_hit_at_k",
                "retrieval_precision",
                "retrieval_recall",
                "error",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.case_id,
                    r.question,
                    r.answer,
                    r.reference_answer,
                    "|".join(r.cited_chunks),
                    f"{r.correctness_score:.4f}",
                    f"{r.faithfulness_score:.4f}",
                    str(r.hallucinated),
                    "" if r.retrieval_hit_at_k is None else f"{r.retrieval_hit_at_k:.4f}",
                    "" if r.retrieval_precision is None else f"{r.retrieval_precision:.4f}",
                    "" if r.retrieval_recall is None else f"{r.retrieval_recall:.4f}",
                    r.error or "",
                ]
            )

    print("\nRAG Evaluation Summary")
    print("======================")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"\nJSON report: {json_path}")
    print(f"CSV report : {csv_path}")

    return json_payload


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Evaluate RAG correctness and hallucination")
    p.add_argument("--benchmark", required=True, help="Path to benchmark JSON file")
    p.add_argument("--api-base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    p.add_argument("--user-id", default="eval-user", help="User id to send in /api/chat")
    p.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"), help="Qdrant URL")
    p.add_argument("--qdrant-collection", default=os.getenv("QDRANT_COLLECTION", "documents"), help="Qdrant collection")
    p.add_argument("--output-dir", default="app/tests/eval_reports", help="Output folder for reports")
    p.add_argument("--timeout-sec", type=int, default=120, help="Request timeout per test case")
    p.add_argument("--use-llm-judge", action="store_true", help="Use Gemini as evaluation judge")
    p.add_argument(
        "--judge-model",
        default=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        help="Gemini model for judging",
    )
    p.add_argument(
        "--heuristic-support-threshold",
        type=float,
        default=0.22,
        help="Heuristic threshold below which answer is flagged as hallucinated",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    run_eval(args)


if __name__ == "__main__":
    main()
