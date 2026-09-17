"""
Embedding helpers for Research Memory.

DeepSeek chat API does NOT provide embeddings. This module uses a local
multilingual model via FastEmbed so we do not need a second paid API key.

Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
Dimension: 384 (verified at runtime via EMBEDDING_DIMENSION)
"""

from __future__ import annotations

import json
from typing import Any

# Confirmed for paraphrase-multilingual-MiniLM-L12-v2
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIMENSION = 384
MAX_CASE_TEXT_CHARS = 6000

_model = None


class EmbeddingUnavailableError(RuntimeError):
    """Raised when the embedding model cannot produce a vector."""

    def __init__(self, message: str = "embedding_unavailable"):
        super().__init__(message)
        self.code = "embedding_unavailable"


def build_case_text(case: dict[str, Any] | None) -> str:
    """
    Turn a Research Case into plain text for embedding.
    Keeps the most useful fields and truncates long blobs.
    """
    case = case if isinstance(case, dict) else {}

    def _as_text(value: Any, limit: int = 1200) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            text = value.strip()
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, indent=None)
            except Exception:
                text = str(value)
        text = " ".join(text.split())
        if len(text) > limit:
            return text[:limit] + "…"
        return text

    parts = [
        "Title:",
        _as_text(case.get("title"), 300),
        "",
        "URL:",
        _as_text(case.get("url"), 300),
        "",
        "Visual:",
        _as_text(case.get("visual")),
        "",
        "Interaction:",
        _as_text(case.get("interaction")),
        "",
        "Frontend:",
        _as_text(case.get("frontend")),
        "",
        "Replication:",
        _as_text(case.get("replication")),
    ]
    text = "\n".join(parts).strip()
    if len(text) > MAX_CASE_TEXT_CHARS:
        text = text[:MAX_CASE_TEXT_CHARS] + "…"
    return text


def _get_model():
    global _model
    if _model is not None:
        return _model
    try:
        from fastembed import TextEmbedding
    except Exception as exc:
        raise EmbeddingUnavailableError(
            f"embedding_unavailable: fastembed import failed ({type(exc).__name__})"
        ) from exc
    try:
        _model = TextEmbedding(model_name=EMBEDDING_MODEL)
    except Exception as exc:
        raise EmbeddingUnavailableError(
            f"embedding_unavailable: model load failed ({type(exc).__name__})"
        ) from exc
    return _model


def embed_text(text: str) -> list[float]:
    """
    Convert text → embedding vector.
    Never invents fake vectors. Raises EmbeddingUnavailableError on failure.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise EmbeddingUnavailableError("embedding_unavailable: empty text")

    try:
        model = _get_model()
        vectors = list(model.embed([cleaned]))
        if not vectors:
            raise EmbeddingUnavailableError("embedding_unavailable: empty response")
        raw = vectors[0]
        vec = [float(x) for x in raw]
    except EmbeddingUnavailableError:
        raise
    except Exception as exc:
        raise EmbeddingUnavailableError(
            f"embedding_unavailable: {type(exc).__name__}"
        ) from exc

    if len(vec) != EMBEDDING_DIMENSION:
        raise EmbeddingUnavailableError(
            f"embedding_unavailable: unexpected dimension {len(vec)} "
            f"(expected {EMBEDDING_DIMENSION})"
        )
    return vec


def reset_embedding_model() -> None:
    """Clear cached model (tests)."""
    global _model
    _model = None
