"""
Chat endpoints for incident-scoped, RAG-grounded assistant responses.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Incident
from app.services.chat_orchestrator import build_chat_context, stream_assistant_deltas

router = APIRouter()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/stream")
def chat_stream(
    incident_id: int = Query(..., gt=0),
    message: str = Query(..., min_length=1),
    conversation_id: Optional[str] = Query(default=None),
    limit_similar: int = Query(default=5, ge=1, le=20),
    limit_runbook: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    def event_stream():
        yield _sse("tool", {"tool": "incident.summarize", "status": "running"})
        try:
            message_id = f"assistant-{uuid.uuid4().hex}"
            context = build_chat_context(
                db,
                incident_id=incident_id,
                limit_similar=limit_similar,
                limit_runbook=limit_runbook,
            )
            chunks = []
            for delta in stream_assistant_deltas(
                user_message=message,
                summary=context.summary,
                next_steps=context.next_steps,
                citations=context.citations,
            ):
                chunks.append(delta)
                yield _sse(
                    "assistant_delta",
                    {
                        "id": message_id,
                        "role": "assistant",
                        "delta": delta,
                        "conversation_id": conversation_id or f"incident-{incident_id}",
                    },
                )
            assistant_message = "".join(chunks).strip()
            if not assistant_message:
                raise RuntimeError("LLM stream returned no content")
            yield _sse(
                "assistant",
                {
                    "id": message_id,
                    "role": "assistant",
                    "content": assistant_message,
                    "citations": context.citations,
                    "conversation_id": conversation_id or f"incident-{incident_id}",
                },
            )
            yield _sse("tool", {"tool": "incident.summarize", "status": "done"})
            yield _sse("done", {"ok": True})
        except Exception as exc:
            yield _sse("tool", {"tool": "incident.summarize", "status": "failed"})
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {"ok": False})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
