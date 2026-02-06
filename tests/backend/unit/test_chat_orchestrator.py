import pytest

from app.services import chat_orchestrator


def _summary_payload():
    return {
        "summary": (
            "Incident #42 \"DB saturation\" is open with severity critical.\n\n"
            "Key alerts:\n"
            "- DB pool reached 95%"
        ),
        "citations": [
            {"type": "alert", "id": 7, "title": "DB pool reached 95%"},
            {"type": "runbook", "source_document": "db-pool.md", "chunk_index": 0, "title": "DB pool"},
        ],
        "next_steps": ["Page on-call and open an incident bridge", "Check runbook: db-pool.md (chunk 0)"],
        "runbook_chunks": [],
    }


@pytest.mark.unit
def test_run_chat_turn_uses_stream_pipeline(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(chat_orchestrator, "summarize_incident", lambda *args, **kwargs: _summary_payload())

    monkeypatch.setattr(
        chat_orchestrator,
        "stream_assistant_deltas",
        lambda **kwargs: iter(["LLM answer with bullets\n", "- one\n", "- two"]),
    )

    turn = chat_orchestrator.run_chat_turn(db=None, incident_id=42, user_message="what now")
    assert turn.assistant_message.startswith("LLM answer")
    assert len(turn.citations) == 2


@pytest.mark.unit
def test_run_chat_turn_raises_when_stream_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(chat_orchestrator, "summarize_incident", lambda *args, **kwargs: _summary_payload())
    monkeypatch.setattr(
        chat_orchestrator,
        "stream_assistant_deltas",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("stream failed")),
    )
    with pytest.raises(RuntimeError, match="stream failed"):
        chat_orchestrator.run_chat_turn(
            db=None,
            incident_id=42,
            user_message="what are the next steps?",
        )


@pytest.mark.unit
def test_collect_assistant_message_raises_on_empty(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(chat_orchestrator, "stream_assistant_deltas", lambda **kwargs: iter([]))
    with pytest.raises(RuntimeError, match="no content"):
        chat_orchestrator.collect_assistant_message(
            user_message="status?",
            summary="summary",
            next_steps=["step1"],
            citations=[],
        )


@pytest.mark.unit
def test_stream_assistant_deltas_uses_openai_stream(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-test")

    class _Event:
        def __init__(self, type_, delta=""):
            self.type = type_
            self.delta = delta

    class _FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter(
                [
                    _Event("response.output_text.delta", "hello "),
                    _Event("response.output_text.delta", "world"),
                    _Event("response.completed", ""),
                ]
            )

    class _FakeResponses:
        @staticmethod
        def stream(**kwargs):
            assert kwargs["model"] == "gpt-test"
            return _FakeStream()

    class _FakeClient:
        def __init__(self):
            self.responses = _FakeResponses()

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeClient)

    deltas = list(
        chat_orchestrator.stream_assistant_deltas(
            user_message="status?",
            summary="summary",
            next_steps=["step1"],
            citations=[],
        )
    )
    assert deltas == ["hello ", "world"]


@pytest.mark.unit
def test_stream_assistant_deltas_raises_when_stream_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class _FailResponses:
        @staticmethod
        def stream(**kwargs):
            raise RuntimeError("stream failed")

    class _FailClient:
        def __init__(self):
            self.responses = _FailResponses()

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FailClient)

    with pytest.raises(RuntimeError, match="stream failed"):
        list(
            chat_orchestrator.stream_assistant_deltas(
                user_message="what are next steps?",
                summary="Incident summary",
                next_steps=["step1", "step2"],
                citations=[],
            )
        )


@pytest.mark.unit
def test_stream_assistant_deltas_raises_on_partial_stream_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class _Event:
        def __init__(self, type_, delta=""):
            self.type = type_
            self.delta = delta

    class _PartialFailStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            yield _Event("response.output_text.delta", "partial ")
            raise RuntimeError("stream interrupted")

    class _PartialFailResponses:
        @staticmethod
        def stream(**kwargs):
            return _PartialFailStream()

    class _PartialFailClient:
        def __init__(self):
            self.responses = _PartialFailResponses()

    import openai

    monkeypatch.setattr(openai, "OpenAI", _PartialFailClient)

    iterator = chat_orchestrator.stream_assistant_deltas(
        user_message="status?",
        summary="Incident summary",
        next_steps=["step1"],
        citations=[],
    )
    assert next(iterator) == "partial "
    with pytest.raises(RuntimeError, match="stream interrupted"):
        next(iterator)
