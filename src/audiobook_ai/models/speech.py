"""SpeechChunk model and deterministic text partitioning for TTS."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from audiobook_ai import config

# Prefer paragraph → dialogue turn → sentence → hard char split.
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


class SpeechChunk(BaseModel):
    """Bounded TTS workload with stable id for resume."""

    id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


def chunking_fingerprint(*, max_chars: int | None = None) -> str:
    """Stable fingerprint of chunking config (invalidates resume on mismatch)."""
    payload = {
        "tts_max_chunk_chars": max_chars
        if max_chars is not None
        else config.TTS_MAX_CHUNK_CHARS,
        "version": 1,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()


def partition_text(
    text: str,
    *,
    max_chars: int | None = None,
    base_metadata: dict[str, Any] | None = None,
    id_prefix: str = "chunk",
    sequence_start: int = 0,
) -> list[SpeechChunk]:
    """Partition ``text`` into SpeechChunks with preferred boundaries.

    Boundaries (preferred order): paragraph → sentence → hard character split.
    Dialogue turns are typically already one call (one Dialogue); when multiple
    paragraphs exist they stay separate when under the limit.
    """
    limit = max_chars if max_chars is not None else config.TTS_MAX_CHUNK_CHARS
    if limit < 1:
        raise ValueError("max_chars must be >= 1")
    cleaned = text.strip()
    if not cleaned:
        return []

    pieces = _split_preferring_boundaries(cleaned, limit)
    meta = dict(base_metadata or {})
    chunks: list[SpeechChunk] = []
    for offset, piece in enumerate(pieces):
        seq = sequence_start + offset
        chunk_id = f"{id_prefix}-{seq:06d}"
        chunks.append(
            SpeechChunk(
                id=chunk_id,
                sequence=seq,
                text=piece,
                metadata=dict(meta),
            )
        )
    return chunks


def partition_dialogues(
    dialogues: list[Any],
    *,
    chapter_id: str,
    max_chars: int | None = None,
    resolve_character_id: Any | None = None,
    sequence_start: int = 0,
) -> list[SpeechChunk]:
    """Convert interpreted dialogues into ordered SpeechChunks.

    Each dialogue turn is preferred as a single chunk when under ``max_chars``.
    """
    limit = max_chars if max_chars is not None else config.TTS_MAX_CHUNK_CHARS
    chunks: list[SpeechChunk] = []
    seq = sequence_start
    for turn_index, dialogue in enumerate(dialogues):
        character_id = None
        if resolve_character_id is not None:
            character_id = resolve_character_id(dialogue)
        elif getattr(dialogue, "speaker_id", None):
            character_id = dialogue.speaker_id
        base_meta: dict[str, Any] = {
            "chapter_id": chapter_id,
            "turn_index": turn_index,
            "emotion": getattr(dialogue.emotion, "value", str(dialogue.emotion)),
        }
        if character_id is not None:
            base_meta["character_id"] = character_id
        if getattr(dialogue, "speaker_name", None):
            base_meta["speaker_name"] = dialogue.speaker_name

        turn_chunks = partition_text(
            dialogue.text,
            max_chars=limit,
            base_metadata=base_meta,
            id_prefix=f"{chapter_id}",
            sequence_start=seq,
        )
        # Prefer stable ids scoped by chapter + global sequence.
        for chunk in turn_chunks:
            chunk.id = f"{chapter_id}-{chunk.sequence:06d}"
            chunks.append(chunk)
            seq = chunk.sequence + 1
    return chunks


def _split_preferring_boundaries(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
    if len(paragraphs) > 1:
        return _pack_units(paragraphs, limit)

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if len(sentences) > 1:
        return _pack_units(sentences, limit)

    return _hard_split(text, limit)


def _pack_units(units: list[str], limit: int) -> list[str]:
    """Greedily pack units under ``limit``, splitting oversized units."""
    out: list[str] = []
    buf = ""
    for unit in units:
        if len(unit) > limit:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(_split_preferring_boundaries(unit, limit))
            continue
        candidate = unit if not buf else f"{buf} {unit}"
        if len(candidate) <= limit:
            buf = candidate
        else:
            out.append(buf)
            buf = unit
    if buf:
        out.append(buf)
    return out


def _hard_split(text: str, limit: int) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)]
