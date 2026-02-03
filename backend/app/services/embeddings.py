"""
Deterministic embeddings for incident similarity.

Uses hashed bag-of-words vectors to avoid external model dependencies.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List

EMBEDDING_DIM = 384
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {"services", "service", "incident"}


def _tokens(text: str) -> List[str]:
    if not text:
        return []
    return [token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS]


def _hash_token(token: str, dim: int) -> tuple[int, int]:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % dim
    sign = 1 if int(digest[8:9], 16) % 2 == 0 else -1
    return idx, sign


def embed_text(text: str, dim: int = EMBEDDING_DIM) -> List[float]:
    """
    Convert text into a deterministic unit-length embedding.
    """
    vec = [0.0] * dim
    for token in _tokens(text):
        idx, sign = _hash_token(token, dim)
        vec[idx] += float(sign)

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def jaccard_similarity(tokens_a: Iterable[str], tokens_b: Iterable[str]) -> float:
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    if not set_a and not set_b:
        return 0.0
    return len(set_a & set_b) / float(len(set_a | set_b))
