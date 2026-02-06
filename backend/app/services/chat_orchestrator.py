"""
Incident-scoped chat orchestration backed by existing RAG summary services.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List

from sqlalchemy.orm import Session

from app.services.incident_summaries import summarize_incident

logger = logging.getLogger(__name__)


@dataclass
class ChatTurnResult:
    assistant_message: str
    citations: List[Dict[str, Any]]
    next_steps: List[str]
    summary: str
    runbook_chunks: List[Dict[str, Any]]


@dataclass
class ChatContext:
    summary: str
    citations: List[Dict[str, Any]]
    next_steps: List[str]
    runbook_chunks: List[Dict[str, Any]]


def _build_assistant_message(user_message: str, summary: str, next_steps: List[str]) -> str:
    normalized = (user_message or "").strip().lower()

    if any(phrase in normalized for phrase in ["next step", "what should", "what now", "action"]):
        if next_steps:
            numbered = "\n".join(f"{idx}. {step}" for idx, step in enumerate(next_steps, start=1))
            return f"Recommended next steps:\n{numbered}"
        return "No next steps were generated for this incident."

    if any(phrase in normalized for phrase in ["summary", "summarize", "recap", "status"]):
        return summary

    if next_steps:
        numbered = "\n".join(f"{idx}. {step}" for idx, step in enumerate(next_steps, start=1))
        return f"{summary}\n\nRecommended next steps:\n{numbered}"
    return summary


def _citation_label(citation: Dict[str, Any], idx: int) -> str:
    ctype = citation.get("type")
    if ctype == "incident":
        return f"[{idx}] incident #{citation.get('id')}: {citation.get('title', '')}".strip()
    if ctype == "alert":
        return f"[{idx}] alert #{citation.get('id')}: {citation.get('title', '')}".strip()
    if ctype == "runbook":
        source = citation.get("source_document", "runbook")
        chunk = citation.get("chunk_index")
        if chunk is None:
            return f"[{idx}] runbook: {source}"
        return f"[{idx}] runbook: {source} (chunk {chunk})"
    return f"[{idx}] source"


def _build_llm_messages(
    user_message: str,
    summary: str,
    next_steps: List[str],
    citations: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    citation_lines = "\n".join(
        _citation_label(citation, idx + 1) for idx, citation in enumerate(citations)
    ) or "None"
    step_lines = "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(next_steps)) or "None"
    context = (
        "Incident Summary:\n"
        f"{summary}\n\n"
        "Candidate Next Steps:\n"
        f"{step_lines}\n\n"
        "Citations:\n"
        f"{citation_lines}"
    )
    system = (
        "You are OpsRelay incident copilot.\n"
        "Produce concise, operator-ready responses.\n"
        "Formatting requirements:\n"
        "- Use short paragraphs.\n"
        "- Use bullet lists for grouped items.\n"
        "- Use numbered lists for ordered actions.\n"
        "- Keep line breaks explicit.\n"
        "- Do not invent facts outside the provided context.\n"
        "- If context is insufficient, state that clearly.\n"
    )
    user = (
        f"Operator question:\n{user_message}\n\n"
        "Use only this context:\n"
        f"{context}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _iter_chunked(text: str, chunk_size: int = 24) -> Iterator[str]:
    if not text:
        return
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def build_chat_context(
    db: Session,
    incident_id: int,
    limit_similar: int = 5,
    limit_runbook: int = 5,
) -> ChatContext:
    result = summarize_incident(
        db,
        incident_id,
        limit_similar=limit_similar,
        limit_runbook=limit_runbook,
    )
    return ChatContext(
        summary=result["summary"],
        citations=result["citations"],
        next_steps=result["next_steps"],
        runbook_chunks=result.get("runbook_chunks", []),
    )


def stream_assistant_deltas(
    user_message: str,
    summary: str,
    next_steps: List[str],
    citations: List[Dict[str, Any]],
) -> Iterator[str]:
    if not os.getenv("OPENAI_API_KEY"):
        fallback_text = _build_assistant_message(user_message, summary, next_steps)
        yield from _iter_chunked(fallback_text)
        return

    model = os.getenv("OPENAI_CHAT_MODEL", "fake-model")
    try:
        from openai import OpenAI

        client = OpenAI()
        with client.responses.stream(
            model=model,
            input=_build_llm_messages(user_message, summary, next_steps, citations),
        ) as stream:
            for event in stream:
                if getattr(event, "type", "") == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
    except Exception as exc:
        logger.warning("LLM stream failed: %s", exc)
        raise


def collect_assistant_message(
    user_message: str,
    summary: str,
    next_steps: List[str],
    citations: List[Dict[str, Any]],
) -> str:
    chunks = list(
        stream_assistant_deltas(
            user_message=user_message,
            summary=summary,
            next_steps=next_steps,
            citations=citations,
        )
    )
    message = "".join(chunks).strip()
    if not message:
        raise RuntimeError("LLM stream returned no content")
    return message


def run_chat_turn(
    db: Session,
    incident_id: int,
    user_message: str,
    limit_similar: int = 5,
    limit_runbook: int = 5,
) -> ChatTurnResult:
    context = build_chat_context(
        db,
        incident_id=incident_id,
        limit_similar=limit_similar,
        limit_runbook=limit_runbook,
    )
    assistant_message = collect_assistant_message(
        user_message=user_message,
        summary=context.summary,
        next_steps=context.next_steps,
        citations=context.citations,
    )

    return ChatTurnResult(
        assistant_message=assistant_message,
        citations=context.citations,
        next_steps=context.next_steps,
        summary=context.summary,
        runbook_chunks=context.runbook_chunks,
    )
