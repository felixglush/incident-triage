"""
Embedding client for OpsRelay.

Calls the ML service /embed endpoint (Qwen3-Embedding-0.6B).
Retains _tokens and jaccard_similarity for BM25 keyword scoring in incident_similarity.py.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, List

import requests as _requests

EMBEDDING_DIM = 1024
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "8"))
EMBED_TIMEOUT = int(os.getenv("EMBED_TIMEOUT", "60"))
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "a", "about", "above", "across", "after", "again", "against", "all",
    "almost", "alone", "along", "already", "also", "although", "always", "am",
    "among", "an", "and", "another", "any", "are", "around", "as", "at",
    "back", "be", "became", "because", "been", "before", "being", "between",
    "but", "by", "can", "cannot", "could", "do", "done", "down", "each",
    "even", "every", "few", "for", "from", "get", "give", "go", "had", "has",
    "have", "he", "her", "here", "him", "his", "how", "i", "if", "in",
    "into", "is", "it", "its", "just", "keep", "last", "less", "made",
    "many", "may", "me", "might", "more", "most", "move", "much", "must",
    "my", "neither", "never", "next", "no", "nobody", "none", "nor", "not",
    "nothing", "now", "of", "off", "often", "on", "once", "one", "only",
    "or", "other", "our", "out", "over", "own", "per", "please", "put",
    "rather", "re", "same", "see", "seem", "seems", "several", "she",
    "should", "since", "so", "some", "still", "such", "take", "than", "that",
    "the", "their", "them", "then", "there", "these", "they", "this",
    "those", "though", "through", "thus", "to", "too", "toward", "two",
    "un", "under", "until", "up", "upon", "us", "very", "via", "was", "we",
    "well", "were", "what", "when", "where", "whether", "which", "while",
    "who", "whom", "why", "will", "with", "within", "without", "would",
    "yet", "you", "your",
}


def _tokens(text: str) -> List[str]:
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def jaccard_similarity(tokens_a: Iterable[str], tokens_b: Iterable[str]) -> float:
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    if not set_a and not set_b:
        return 0.0
    return len(set_a & set_b) / float(len(set_a | set_b))


def embed_texts(texts: List[str], mode: str = "document") -> List[List[float]]:
    """Batch embed via ML service. mode='document' for ingestion, 'query' for retrieval."""
    if not texts:
        return []
    results: List[List[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        try:
            response = _requests.post(
                f"{ML_SERVICE_URL}/embed",
                json={"texts": batch, "mode": mode},
                timeout=EMBED_TIMEOUT,
            )
            response.raise_for_status()
        except _requests.RequestException as exc:
            raise RuntimeError(f"ML service embedding call failed: {exc}") from exc
        results.extend(response.json()["embeddings"])
    return results


def embed_text(text: str, mode: str = "document") -> List[float]:
    """Embed a single text. Returns zero vector for empty input."""
    if not text or not text.strip():
        return [0.0] * EMBEDDING_DIM
    return embed_texts([text], mode=mode)[0]
