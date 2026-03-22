"""Unit tests for embeddings.py HTTP client."""
import pytest
from unittest.mock import patch, MagicMock

import app.services.embeddings as emb_module
from app.services.embeddings import embed_text, embed_texts, EMBEDDING_DIM


def _mock_post(embeddings: list[list[float]]):
    """Helper: returns a mock requests.post that yields given embeddings."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"embeddings": embeddings}
    mock = MagicMock(return_value=mock_resp)
    return mock


@pytest.mark.unit
def test_embedding_dim_is_1024():
    assert EMBEDDING_DIM == 1024


@pytest.mark.unit
def test_embed_text_calls_ml_service():
    vec = [0.1] * 1024
    with patch("app.services.embeddings._requests.post", _mock_post([vec])) as mock_post:
        result = embed_text("redis connection pool exhausted")
    assert result == vec
    call_json = mock_post.call_args.kwargs["json"]
    assert call_json["mode"] == "document"
    assert call_json["texts"] == ["redis connection pool exhausted"]


@pytest.mark.unit
def test_embed_text_query_mode():
    vec = [0.2] * 1024
    with patch("app.services.embeddings._requests.post", _mock_post([vec])) as mock_post:
        result = embed_text("high cpu", mode="query")
    assert result == vec
    assert mock_post.call_args.kwargs["json"]["mode"] == "query"


@pytest.mark.unit
def test_embed_text_empty_returns_zero_vector():
    """Empty input must not call the ML service."""
    with patch("app.services.embeddings._requests.post") as mock_post:
        result = embed_text("")
    assert result == [0.0] * 1024
    mock_post.assert_not_called()


@pytest.mark.unit
def test_embed_texts_batches_correctly():
    """With EMBED_BATCH_SIZE=2 and 5 texts, expect 3 HTTP calls."""
    vecs = [[float(i)] * 1024 for i in range(5)]
    call_count = 0

    def fake_post(url, json, timeout):
        nonlocal call_count
        batch = json["texts"]
        start = call_count * 2
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"embeddings": vecs[start: start + len(batch)]}
        return mock_resp

    with patch("app.services.embeddings._requests.post", fake_post):
        with patch.object(emb_module, "EMBED_BATCH_SIZE", 2):
            result = embed_texts(["t1", "t2", "t3", "t4", "t5"])

    assert call_count == 3
    assert len(result) == 5


@pytest.mark.unit
def test_embed_texts_empty_list():
    with patch("app.services.embeddings._requests.post") as mock_post:
        result = embed_texts([])
    assert result == []
    mock_post.assert_not_called()


@pytest.mark.unit
def test_embed_texts_ml_service_error_raises_runtime_error():
    import requests
    with patch("app.services.embeddings._requests.post",
               side_effect=requests.RequestException("connection refused")):
        with pytest.raises(RuntimeError, match="ML service embedding call failed"):
            embed_texts(["some text"])


@pytest.mark.unit
def test_jaccard_similarity_retained():
    """jaccard_similarity must still be importable — used by incident_similarity.py."""
    from app.services.embeddings import jaccard_similarity
    assert jaccard_similarity(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)


@pytest.mark.unit
def test_tokens_retained():
    """_tokens must still be importable — used by incident_similarity.py."""
    from app.services.embeddings import _tokens
    tokens = _tokens("Redis connection pool exhausted")
    assert "redis" in tokens
    assert "connection" in tokens
