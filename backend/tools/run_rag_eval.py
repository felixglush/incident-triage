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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from langsmith import traceable, Client
from langsmith.wrappers import wrap_openai

from app.database import get_db_context
from app.services.embeddings import embed_text
from app.services.incident_similarity import find_similar_runbook_chunks


@dataclass
class EvalCase:
    id: str
    question: str
    expected_source_document: str
    expected_contains: str
    expected_answer_contains: str | None = None
    gold_answer: str | None = None


def load_cases(path: Path) -> List[EvalCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        cases.append(EvalCase(**payload))
    return cases


def load_env_file(path: Path) -> None:
    if path.exists():
        load_dotenv(dotenv_path=path, override=False)


def build_context(retrieved: Iterable[Dict[str, Any]]) -> str:
    context = []
    for item in retrieved:
        chunk = item["chunk"]
        context.append(f"[{chunk.source_document}] {chunk.title or ''}\n{chunk.content}")
    return "\n\n".join(context)


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
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required to run evaluations.")
    dataset_path = Path(args.dataset)
    cases = load_cases(dataset_path)
    results_payload = []
    client = Client()

    failures = []
    with get_db_context() as db:
        for case in cases:
            query_embedding = embed_text(case.question)
            retrieved = find_similar_runbook_chunks(db, query_embedding, case.question, limit=args.limit)
            if args.debug:
                print(f"\n[{case.id}] Query: {case.question}")
                for idx, item in enumerate(retrieved, start=1):
                    chunk = item["chunk"]
                    snippet = (chunk.content or "").replace("\n", " ").strip()[:160]
                    print(
                        f"  {idx}. {chunk.source_document} | score={item['score']:.3f} | "
                        f"title={chunk.title or ''} | {snippet}"
                    )
            answer = llm_answer(case.question, retrieved)
            metrics = llm_judge(case.question, answer, retrieved, case.gold_answer)

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

            if any(
                score is not None and score < 0.6
                for score in [retrieval_relevance, answer_relevance, groundedness, correctness]
            ):
                failures.append(case.id)

    if args.log_langsmith:
        maybe_log_langsmith(results_payload)
    try:
        client.flush()
    except Exception:
        pass

    if failures:
        print("\nFailures (score < 0.6):")
        for case_id in failures:
            print(f"- {case_id}")
    else:
        print("\nAll evals passed (>= 0.6).")


if __name__ == "__main__":
    main()
