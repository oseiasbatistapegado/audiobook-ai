"""Embedding service for speaker resolution (fallback).

Uses sentence-transformers to compute semantic embeddings for descriptive
alias resolution. The cache is per-character (not per-chapter).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np


class EmbeddingModel(Protocol):
    """Minimal surface for an embedding model (mockable)."""

    def encode(
        self,
        sentences: list[str],
        *,
        normalize_embeddings: bool = False,
    ) -> np.ndarray: ...


class SpeakerEmbeddingService:
    """Wrapper around sentence-transformers for speaker resolution.

    Provides:
    - ``encode(text)`` → embedding vector
    - ``cosine_similarity(a, b)`` → float similarity
    - ``resolve_descriptive_aliases(text, profiles, top_k)`` → ranked speakers
    - ``save_embedding(speaker_id, embedding)`` / ``load_embedding(speaker_id)``

    If sentence-transformers is not installed, all operations degrade to
    a no-op (no error).
    """

    def __init__(
        self,
        model: EmbeddingModel | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._model = model
        self._cache_dir = cache_dir
        self._cache: dict[str, list[float]] = {}

    @classmethod
    def load(
        cls,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
        *,
        cache_dir: Path | None = None,
    ) -> SpeakerEmbeddingService:
        """Load the embedding service.

        Falls back gracefully if sentence-transformers is unavailable.
        """
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name)
            return cls(model=model, cache_dir=cache_dir)
        except ImportError:
            return cls(model=None, cache_dir=cache_dir)

    def encode(self, text: str) -> list[float] | None:
        """Encode a text string into a float list.

        Returns None if no model is loaded.
        """
        if self._model is None:
            return None
        arr = self._model.encode([text], normalize_embeddings=True)
        return arr[0].tolist()

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        if not a or not b:
            return 0.0
        a_arr = np.array(a)
        b_arr = np.array(b)
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))

    def resolve_descriptive_aliases(
        self,
        text: str,
        profiles: list[Any],
        top_k: int = 3,
    ) -> list[tuple[str, float]]:
        """Resolve descriptive aliases to speaker_ids using embeddings.

        Args:
            text: The unit text to match against.
            profiles: List of character profiles.
            top_k: Number of top matches to return.

        Returns:
            List of (speaker_id, similarity) tuples, sorted by similarity desc.
        """
        if self._model is None:
            return []

        text_embedding = self.encode(text)
        if text_embedding is None:
            return []

        results: list[tuple[str, float]] = []
        for profile in profiles:
            # Try all aliases + name.
            candidates = [profile.name, *profile.aliases]
            for candidate in candidates:
                emb = self.encode(candidate)
                if emb is None:
                    continue
                sim = self.cosine_similarity(text_embedding, emb)
                results.append((profile.id, sim))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def save_embedding(self, speaker_id: str, embedding: list[float]) -> None:
        """Save an embedding to disk cache."""
        self._cache[speaker_id] = embedding
        if self._cache_dir is not None:
            cache_path = self._cache_dir / f"embedding_{speaker_id}.npy"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(str(cache_path), np.array(embedding))

    def load_embedding(self, speaker_id: str) -> list[float] | None:
        """Load an embedding from disk cache or memory cache."""
        if speaker_id in self._cache:
            return self._cache[speaker_id]

        if self._cache_dir is not None:
            cache_path = self._cache_dir / f"embedding_{speaker_id}.npy"
            if cache_path.is_file():
                arr = np.load(str(cache_path))
                self._cache[speaker_id] = arr.tolist()
                return self._cache[speaker_id]

        return None


def safe_embedding_encode(
    text: str,
    service: SpeakerEmbeddingService | None,
) -> list[float] | None:
    """Safely encode text, returning None on any error."""
    if service is None:
        return None
    try:
        return service.encode(text)
    except Exception:  # noqa: BLE001
        return None
