#!/usr/bin/env python3
"""
Local RAG evaluation runner.

Evaluates retrieval relevance and (optionally) answer relevance / groundedness.
Can log results to LangSmith when LANGCHAIN_API_KEY is configured.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from statistics import mean
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from langsmith import traceable, Client
from langsmith.wrappers import wrap_openai

from app.database import get_db_context
from app.models import Alert
from app.services.embeddings import embed_text
from app.services.incident_similarity import find_similar_runbook_chunks
from app.services.chat_orchestrator import run_chat_turn
from app.models import Incident, SeverityLevel, IncidentStatus


@dataclass
class EvalCase:
    id: str
    question: str | None = None
    expected_source_document: str | None = None
    expected_contains: str | None = None
    expected_answer_contains: str | None = None
    gold_answer: str | None = None
    mode: str = "rag_single"
    incident_id: int | None = None
    turns: list[dict[str, Any]] | None = None
    create_incident: dict[str, Any] | None = None


def load_cases(path: Path) -> List[EvalCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        payload.setdefault("mode", "rag_single")
        cases.append(EvalCase(**payload))
    return cases


def _coerce_severity(value: str | None) -> SeverityLevel:
    raw = (value or "warning").strip().lower()
    return SeverityLevel(raw)


def _coerce_status(value: str | None) -> IncidentStatus:
    raw = (value or "open").strip().lower()
    return IncidentStatus(raw)


def load_env_file(path: Path) -> None:
    if path.exists():
        load_dotenv(dotenv_path=path, override=False)


def build_context(retrieved: Iterable[Dict[str, Any]]) -> str:
    context = []
    for item in retrieved:
        if "chunk" in item:
            chunk = item["chunk"]
            context.append(f"[{chunk.source_document}] {chunk.title or ''}\n{chunk.content}")
            continue
        source = item.get("source_document") or item.get("source") or "context"
        title = item.get("title") or ""
        text = item.get("text") or item.get("content") or ""
        context.append(f"[{source}] {title}\n{text}".strip())
    return "\n\n".join(context)


def build_chat_judge_context(db, citations: list[dict[str, Any]], runbook_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in runbook_chunks:
        chunk = item.get("chunk")
        if not chunk:
            continue
        key = f"runbook:{chunk.source_document}:{chunk.chunk_index}"
        if key in seen:
            continue
        seen.add(key)
        contexts.append(
            {
                "source": chunk.source_document,
                "title": chunk.title or "",
                "text": chunk.content or "",
            }
        )

    for cite in citations:
        cite_type = cite.get("type")
        if cite_type == "alert":
            alert_id = cite.get("id")
            if not alert_id:
                continue
            key = f"alert:{alert_id}"
            if key in seen:
                continue
            alert = db.query(Alert).filter(Alert.id == alert_id).first()
            if not alert:
                continue
            seen.add(key)
            contexts.append(
                {
                    "source": f"alert:{alert.id}",
                    "title": alert.title or "",
                    "text": alert.message or "",
                }
            )
        elif cite_type == "incident":
            incident_id = cite.get("id")
            if not incident_id:
                continue
            key = f"incident:{incident_id}"
            if key in seen:
                continue
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if not incident:
                continue
            seen.add(key)
            contexts.append(
                {
                    "source": f"incident:{incident.id}",
                    "title": incident.title or "",
                    "text": incident.summary or "",
                }
            )

    return contexts


@traceable(run_type="llm", name="Generate Answer")
def llm_answer(question: str, retrieved: Iterable[Dict[str, Any]]) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for LLM evaluations.")

    try:
        from openai import OpenAI
    except Exception:
        raise SystemExit("OpenAI SDK is not installed. Add openai to requirements.")

    client = wrap_openai(OpenAI())
    context_text = build_context(retrieved)
    model = os.getenv("OPENAI_RAG_MODEL", "gpt-5.2")

    prompt = (
        "You are a concise incident assistant. Answer the question using only the retrieved context.\n"
        "If the answer is not present, say you do not have enough information.\n\n"
        f"Question:\n{question}\n\n"
        f"Retrieved Context:\n{context_text}\n\n"
        "Answer:"
    )

    response = client.responses.create(
        model=model,
        input=prompt,
    )
    return response.output_text.strip()


@traceable(run_type="llm", name="Judge Answer")
def llm_judge(
    question: str,
    answer: str,
    retrieved: Iterable[Dict[str, Any]],
    gold_answer: str | None = None,
) -> Dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for LLM evaluations.")

    try:
        from openai import OpenAI
    except Exception:
        raise SystemExit("OpenAI SDK is not installed. Add openai to requirements.")

    client = wrap_openai(OpenAI())
    context_text = build_context(retrieved)

    gold_block = f"\nGold Answer:\n{gold_answer}\n\n" if gold_answer else ""
    prompt = (
        "You are evaluating a RAG system.\n"
        "Return JSON with four scores in [0,1]:\n"
        "- retrieval_relevance: do the retrieved chunks contain information relevant to the question?\n"
        "- answer_relevance: does the answer address the question?\n"
        "- groundedness: is the answer supported by the retrieved context?\n\n"
        f"Question:\n{question}\n\n"
        f"Answer:\n{answer}\n\n"
        f"Retrieved Context:\n{context_text}\n\n"
        f"{gold_block}"
        "If a gold_answer is provided, also score:\n"
        "- correctness: is the answer consistent with the gold answer?\n\n"
        "Return only JSON like: {\"retrieval_relevance\": 0.7, \"answer_relevance\": 0.7, \"groundedness\": 0.8, \"correctness\": 0.7}\n"
    )

    model = os.getenv("OPENAI_EVAL_MODEL", "gpt-5.2")
    response = client.responses.create(
        model=model,
        input=prompt,
    )
    raw = response.output_text.strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"retrieval_relevance": None, "answer_relevance": None, "groundedness": None, "correctness": None, "raw": raw}


def maybe_log_langsmith(cases: List[Dict[str, Any]]) -> None:
    if not os.getenv("LANGSMITH_API_KEY"):
        return
    try:
        from langsmith import Client
        from langsmith.utils import LangSmithConflictError
    except Exception:
        print("LangSmith not installed. Skipping LangSmith logging.")
        return

    client = Client()
    dataset_name = os.getenv("LANGSMITH_PROJECT", "opsrelay-rag-evals")
    try:
        dataset = client.create_dataset(dataset_name=dataset_name)
    except LangSmithConflictError:
        dataset = client.read_dataset(dataset_name=dataset_name)
    for row in cases:
        client.create_example(
            inputs={"question": row["question"]},
            outputs={
                "retrieved_docs": row["retrieved_docs"],
                "answer": row["answer"],
            },
            metadata=row["metrics"],
            dataset_id=dataset.id,
        )


@traceable(run_type="chain", name="RAG Eval Run")
def main() -> None:
    parser = argparse.ArgumentParser(description="Run local RAG evaluation")
    parser.add_argument("--dataset", required=True, help="Path to eval JSONL")
    parser.add_argument("--limit", type=int, default=5, help="Top-k retrieval")
    parser.add_argument("--env-file", default=".env", help="Optional .env file to load")
    parser.add_argument("--log-langsmith", action="store_true", help="Log to LangSmith if configured")
    parser.add_argument("--debug", action="store_true", help="Print retrieved chunks and scores")
    parser.add_argument("--fail-under", type=float, default=None, help="Fail if any score < threshold")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    dataset_path = Path(args.dataset)
    cases = load_cases(dataset_path)
    requires_llm = any(case.mode != "chat_multiturn" for case in cases)
    if requires_llm and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required to run LLM-based evaluations.")
    results_payload = []
    client = Client()

    failures = []
    metric_values: Dict[str, List[float]] = {
        "retrieval_relevance": [],
        "answer_relevance": [],
        "groundedness": [],
        "correctness": [],
    }
    with get_db_context() as db:
        for case in cases:
            if case.mode == "chat_multiturn":
                incident_id: Optional[int] = case.incident_id
                if incident_id is None and case.create_incident:
                    payload = case.create_incident
                    incident = Incident(
                        title=payload.get("title", "the and of"),
                        severity=_coerce_severity(payload.get("severity")),
                        status=_coerce_status(payload.get("status")),
                        assigned_team=payload.get("assigned_team", "platform"),
                        affected_services=payload.get("affected_services", []),
                    )
                    db.add(incident)
                    db.commit()
                    db.refresh(incident)
                    incident_id = incident.id
                if incident_id is None:
                    raise SystemExit(f"{case.id}: incident_id or create_incident is required for chat_multiturn")

                turn_rows = case.turns or []
                for turn_idx, turn in enumerate(turn_rows, start=1):
                    question = turn["question"]
                    turn_result = run_chat_turn(
                        db,
                        incident_id=incident_id,
                        user_message=question,
                        limit_similar=args.limit,
                        limit_runbook=args.limit,
                    )
                    assistant_text = turn_result.assistant_message
                    citations_count = len(turn_result.citations)
                    has_citations = citations_count > 0

                    expected_contains = turn.get("expected_answer_contains")
                    contains_ok = True
                    if expected_contains:
                        contains_ok = expected_contains.lower() in assistant_text.lower()

                    expected_has_citations = turn.get("expected_has_citations")
                    citations_ok = True
                    if expected_has_citations is not None:
                        citations_ok = bool(expected_has_citations) == has_citations

                    llm_metrics: Dict[str, Any] = {}
                    if os.getenv("OPENAI_API_KEY"):
                        judge_context = build_chat_judge_context(db, turn_result.citations, turn_result.runbook_chunks)
                        llm_metrics = llm_judge(
                            question=question,
                            answer=assistant_text,
                            retrieved=judge_context,
                            gold_answer=turn.get("gold_answer"),
                        )

                    turn_id = f"{case.id}.turn-{turn_idx}"
                    passed = contains_ok and citations_ok
                    print(
                        f"[{turn_id}] contains_ok={contains_ok} citations_ok={citations_ok} "
                        f"citations_count={citations_count}"
                    )

                    results_payload.append(
                        {
                            "id": turn_id,
                            "question": question,
                            "retrieved_docs": [],
                            "answer": assistant_text,
                            "metrics": {
                                "contains_ok": contains_ok,
                                "citations_ok": citations_ok,
                                "citations_count": citations_count,
                                **llm_metrics,
                            },
                        }
                    )
                    for key in ["retrieval_relevance", "answer_relevance", "groundedness", "correctness"]:
                        score = llm_metrics.get(key)
                        if score is not None:
                            metric_values[key].append(score)
                    if not passed:
                        failures.append(turn_id)
                continue

            query_embedding = embed_text(case.question or "")
            retrieved = find_similar_runbook_chunks(db, query_embedding, case.question or "", limit=args.limit)
            if args.debug:
                print(f"\n[{case.id}] Query: {case.question}")
                for idx, item in enumerate(retrieved, start=1):
                    chunk = item["chunk"]
                    snippet = (chunk.content or "").replace("\n", " ").strip()[:160]
                    print(
                        f"  {idx}. {chunk.source_document} | score={item['score']:.3f} | "
                        f"title={chunk.title or ''} | {snippet}"
                    )
            answer = llm_answer(case.question or "", retrieved)
            metrics = llm_judge(case.question or "", answer, retrieved, case.gold_answer)

            results_payload.append({
                "id": case.id,
                "question": case.question,
                "retrieved_docs": [
                    {
                        "source_document": item["chunk"].source_document,
                        "title": item["chunk"].title,
                        "score": item["score"],
                    }
                    for item in retrieved
                ],
                "answer": answer,
                "metrics": metrics,
            })

            retrieval_relevance = metrics.get("retrieval_relevance")
            groundedness = metrics.get("groundedness")
            answer_relevance = metrics.get("answer_relevance")
            correctness = metrics.get("correctness")
            print(
                f"[{case.id}] retrieval_relevance={retrieval_relevance} "
                f"answer_relevance={answer_relevance} groundedness={groundedness} correctness={correctness}"
            )

            for key, score in [
                ("retrieval_relevance", retrieval_relevance),
                ("answer_relevance", answer_relevance),
                ("groundedness", groundedness),
                ("correctness", correctness),
            ]:
                if score is not None:
                    metric_values[key].append(score)

            if args.fail_under is not None and any(
                score is not None and score < args.fail_under
                for score in [retrieval_relevance, answer_relevance, groundedness, correctness]
            ):
                failures.append(case.id)

    if args.log_langsmith:
        maybe_log_langsmith(results_payload)
    try:
        client.flush()
    except Exception:
        pass

    total_cases = len(cases)
    passed_cases = total_cases - len(failures)
    pass_rate = (passed_cases / total_cases) * 100 if total_cases else 0.0

    print("\nSummary:")
    print(f"- Cases: {passed_cases}/{total_cases} passed ({pass_rate:.1f}%)")
    for key, values in metric_values.items():
        if values:
            print(f"- {key}: avg {mean(values):.2f}")
        else:
            print(f"- {key}: avg n/a")

    if args.fail_under is not None:
        if failures:
            print(f"\nFailures (score < {args.fail_under}):")
            for case_id in failures:
                print(f"- {case_id}")
            sys.exit(1)
        else:
            print(f"\nAll evals passed (>= {args.fail_under}).")


if __name__ == "__main__":
    main()
