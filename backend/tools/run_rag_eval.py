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


def llm_answer(question: str, retrieved: Iterable[Dict[str, Any]]) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for LLM evaluations.")

    try:
        from openai import OpenAI
    except Exception:
        raise SystemExit("OpenAI SDK is not installed. Add openai to requirements.")

    client = OpenAI()
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


def llm_judge(question: str, answer: str, retrieved: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for LLM evaluations.")

    try:
        from openai import OpenAI
    except Exception:
        raise SystemExit("OpenAI SDK is not installed. Add openai to requirements.")

    client = OpenAI()
    context_text = build_context(retrieved)

    prompt = (
        "You are evaluating a RAG system.\n"
        "Return JSON with three scores in [0,1]:\n"
        "- retrieval_relevance: do the retrieved chunks contain information relevant to the question?\n"
        "- answer_relevance: does the answer address the question?\n"
        "- groundedness: is the answer supported by the retrieved context?\n\n"
        f"Question:\n{question}\n\n"
        f"Answer:\n{answer}\n\n"
        f"Retrieved Context:\n{context_text}\n\n"
        "Return only JSON like: {\"retrieval_relevance\": 0.7, \"answer_relevance\": 0.7, \"groundedness\": 0.8}\n"
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
        return {"retrieval_relevance": None, "answer_relevance": None, "groundedness": None, "raw": raw}


def maybe_log_langsmith(cases: List[Dict[str, Any]]) -> None:
    if not os.getenv("LANGSMITH_API_KEY"):
        return
    try:
        from langsmith import Client
    except Exception:
        print("LangSmith not installed. Skipping LangSmith logging.")
        return

    client = Client()
    dataset_name = os.getenv("LANGSMITH_PROJECT", "opsrelay-rag-evals")
    dataset = client.create_dataset(dataset_name=dataset_name)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local RAG evaluation")
    parser.add_argument("--dataset", required=True, help="Path to eval JSONL")
    parser.add_argument("--limit", type=int, default=5, help="Top-k retrieval")
    parser.add_argument("--env-file", default=".env", help="Optional .env file to load")
    parser.add_argument("--log-langsmith", action="store_true", help="Log to LangSmith if configured")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required to run evaluations.")
    dataset_path = Path(args.dataset)
    cases = load_cases(dataset_path)
    results_payload = []

    with get_db_context() as db:
        for case in cases:
            query_embedding = embed_text(case.question)
            retrieved = find_similar_runbook_chunks(db, query_embedding, case.question, limit=args.limit)
            answer = llm_answer(case.question, retrieved)
            metrics = llm_judge(case.question, answer, retrieved)

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

            print(f"[{case.id}] retrieval_relevance={metrics.get('retrieval_relevance')} groundedness={metrics.get('groundedness')}")

    if args.log_langsmith:
        maybe_log_langsmith(results_payload)


if __name__ == "__main__":
    main()
