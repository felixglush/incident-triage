import pytest

from app.models import RunbookChunk
from app.services.embeddings import embed_text
from app.services.incident_similarity import find_similar_runbook_chunks


@pytest.mark.integration
class TestRagRetrieval:
    def test_runbook_retrieval_prefers_relevant_chunk(self, db_session):
        db_session.add(
            RunbookChunk(
                source_document="db.md",
                chunk_index=0,
                source="runbooks",
                title="Database Connection Pool Saturation",
                content="Connection pool exhausted errors and mitigation steps.",
                embedding=embed_text("Connection pool exhausted errors and mitigation steps."),
                doc_metadata={"tags": ["db"]},
            )
        )
        db_session.add(
            RunbookChunk(
                source_document="api.md",
                chunk_index=0,
                source="runbooks",
                title="API Gateway Restart",
                content="Restarting the API gateway safely.",
                embedding=embed_text("Restarting the API gateway safely."),
                doc_metadata={"tags": ["api"]},
            )
        )
        db_session.commit()

        query = "connection pool exhausted"
        results = find_similar_runbook_chunks(db_session, embed_text(query), query, limit=1)
        assert results
        assert "Database Connection Pool" in results[0]["chunk"].title

    def test_runbook_retrieval_excludes_other_sources(self, db_session):
        db_session.add(
            RunbookChunk(
                source_document="notion.md",
                chunk_index=0,
                source="notion",
                title="Incident Response Playbook",
                content="Escalation steps for on-call.",
                embedding=embed_text("Escalation steps for on-call."),
                doc_metadata={"tags": ["notion"]},
            )
        )
        db_session.add(
            RunbookChunk(
                source_document="runbook.md",
                chunk_index=0,
                source="runbooks",
                title="Queue Backlog",
                content="Queue backlog troubleshooting steps.",
                embedding=embed_text("Queue backlog troubleshooting steps."),
                doc_metadata={"tags": ["runbook"]},
            )
        )
        db_session.commit()

        query = "queue backlog"
        results = find_similar_runbook_chunks(db_session, embed_text(query), query, limit=5)
        assert all(item["chunk"].source == "runbooks" for item in results)

    def test_rerank_boosts_title_match(self, db_session):
        content = "Pool usage is high and nearing saturation."
        db_session.add(
            RunbookChunk(
                source_document="pooling.md",
                chunk_index=0,
                source="runbooks",
                title="Pooling instructions",
                content=content,
                embedding=embed_text(content),
                doc_metadata={"tags": ["db"]},
            )
        )
        db_session.add(
            RunbookChunk(
                source_document="scaling.md",
                chunk_index=0,
                source="runbooks",
                title="Scaling notes",
                content=content,
                embedding=embed_text(content),
                doc_metadata={"tags": ["db"]},
            )
        )
        db_session.commit()

        query = "pool"
        results = find_similar_runbook_chunks(db_session, embed_text(query), query, limit=2)
        assert results
        assert results[0]["chunk"].title == "Pooling instructions"

    def test_bm25_filters_non_matching_queries(self, db_session):
        db_session.add(
            RunbookChunk(
                source_document="auth.md",
                chunk_index=0,
                source="runbooks",
                title="Auth Outage",
                content="Auth validation failures and token errors.",
                embedding=embed_text("Auth validation failures and token errors."),
                doc_metadata={"tags": ["auth"]},
            )
        )
        db_session.commit()

        query = "the and of"
        results = find_similar_runbook_chunks(db_session, embed_text(query), query, limit=5)
        assert results == []
