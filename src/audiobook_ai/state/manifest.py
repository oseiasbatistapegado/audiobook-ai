"""Book-scoped speech chunk manifest for resume and ordered merge."""

from __future__ import annotations

import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from audiobook_ai import config
from audiobook_ai.models.speech import SpeechChunk, chunking_fingerprint


class ChunkStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ManifestChunkEntry(BaseModel):
    id: str
    sequence: int
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: ChunkStatus = ChunkStatus.PENDING
    audio_path: str | None = None
    attempts: int = 0
    error: str | None = None


class SpeechManifest(BaseModel):
    version: int = 1
    book_id: str
    chunking_fingerprint: str
    chunks: list[ManifestChunkEntry] = Field(default_factory=list)

    def ordered_chunks(self) -> list[ManifestChunkEntry]:
        return sorted(self.chunks, key=lambda c: c.sequence)

    def get(self, chunk_id: str) -> ManifestChunkEntry | None:
        for entry in self.chunks:
            if entry.id == chunk_id:
                return entry
        return None


def create_manifest(
    book_id: str,
    chunks: list[SpeechChunk],
    *,
    fingerprint: str | None = None,
) -> SpeechManifest:
    fp = fingerprint if fingerprint is not None else chunking_fingerprint()
    entries = [
        ManifestChunkEntry(
            id=chunk.id,
            sequence=chunk.sequence,
            text=chunk.text,
            metadata=dict(chunk.metadata),
            status=ChunkStatus.PENDING,
        )
        for chunk in chunks
    ]
    return SpeechManifest(
        book_id=book_id,
        chunking_fingerprint=fp,
        chunks=entries,
    )


def load_manifest(path: Path) -> SpeechManifest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return SpeechManifest.model_validate(data)


def save_manifest(manifest: SpeechManifest, path: Path) -> None:
    """Atomically write manifest JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump(mode="json")
    raw = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".manifest-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def mark_completed(
    manifest: SpeechManifest,
    chunk_id: str,
    audio_path: Path | str,
) -> SpeechManifest:
    entry = manifest.get(chunk_id)
    if entry is None:
        raise KeyError(f"unknown chunk id: {chunk_id}")
    entry.status = ChunkStatus.COMPLETED
    entry.audio_path = str(audio_path)
    entry.error = None
    return manifest


def mark_failed(
    manifest: SpeechManifest,
    chunk_id: str,
    error: str,
) -> SpeechManifest:
    entry = manifest.get(chunk_id)
    if entry is None:
        raise KeyError(f"unknown chunk id: {chunk_id}")
    entry.status = ChunkStatus.FAILED
    entry.attempts += 1
    entry.error = error
    return manifest


def is_chunk_valid(
    entry: ManifestChunkEntry,
    *,
    book_root: Path,
) -> bool:
    """Completed + existing non-empty audio file."""
    if entry.status is not ChunkStatus.COMPLETED:
        return False
    if not entry.audio_path:
        return False
    path = Path(entry.audio_path)
    if not path.is_absolute():
        path = book_root / path
    return path.is_file() and path.stat().st_size > 0


def pending_chunks(
    manifest: SpeechManifest,
    *,
    book_root: Path,
    current_fingerprint: str | None = None,
) -> list[ManifestChunkEntry]:
    """Return chunks that need (re)generation.

    Fingerprint mismatch → all chunks treated as pending (no blind reuse).
    Invalid/missing completed audio → regenerate that chunk.
    """
    fp = current_fingerprint if current_fingerprint is not None else chunking_fingerprint()
    if manifest.chunking_fingerprint != fp:
        return list(manifest.ordered_chunks())

    pending: list[ManifestChunkEntry] = []
    for entry in manifest.ordered_chunks():
        if is_chunk_valid(entry, book_root=book_root):
            continue
        if entry.status is ChunkStatus.COMPLETED:
            entry.status = ChunkStatus.PENDING
            entry.audio_path = None
        pending.append(entry)
    return pending


def completed_audio_segments(
    manifest: SpeechManifest,
    *,
    book_root: Path,
) -> list[tuple[ManifestChunkEntry, Path]]:
    """Ordered (entry, path) for merge — order from manifest, not readdir."""
    result: list[tuple[ManifestChunkEntry, Path]] = []
    for entry in manifest.ordered_chunks():
        if not is_chunk_valid(entry, book_root=book_root):
            raise ValueError(f"chunk {entry.id} not completed/valid for merge")
        path = Path(entry.audio_path)  # type: ignore[arg-type]
        if not path.is_absolute():
            path = book_root / path
        result.append((entry, path))
    return result


def relative_audio_path(sequence: int) -> str:
    return f"{config.AUDIO_SUBDIR}/chunk-{sequence:06d}.wav"
