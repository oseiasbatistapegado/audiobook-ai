"""Tests for SpeechChunk partitioning and manifest resume."""

from __future__ import annotations

from pathlib import Path

import pytest

from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.speech import (
    chunking_fingerprint,
    partition_dialogues,
    partition_text,
)
from audiobook_ai.state.manifest import (
    ChunkStatus,
    create_manifest,
    is_chunk_valid,
    load_manifest,
    mark_completed,
    pending_chunks,
    save_manifest,
)
from audiobook_ai.utils.workdir import ensure_book_work_dir
from audiobook_ai.voice.book_id import compute_book_id


def test_chunk_ids_stable_and_deterministic() -> None:
    text = "First sentence. Second sentence. Third one here."
    a = partition_text(text, max_chars=40, id_prefix="ch1")
    b = partition_text(text, max_chars=40, id_prefix="ch1")
    assert [c.id for c in a] == [c.id for c in b]
    assert [c.sequence for c in a] == list(range(len(a)))
    assert all(len(c.text) <= 40 for c in a)


def test_size_limit_respected_with_hard_split() -> None:
    text = "x" * 1200
    chunks = partition_text(text, max_chars=100)
    assert len(chunks) == 12
    assert all(len(c.text) <= 100 for c in chunks)


def test_dialogue_turn_stays_single_when_under_limit() -> None:
    dialogues = [
        Dialogue(speaker_name="Hero", emotion=Emotion.HAPPY, text="Olá, mundo!"),
    ]
    chunks = partition_dialogues(dialogues, chapter_id="ch-1", max_chars=500)
    assert len(chunks) == 1
    assert chunks[0].id == "ch-1-000000"
    assert chunks[0].metadata["chapter_id"] == "ch-1"


def test_fingerprint_changes_with_max_chars() -> None:
    assert chunking_fingerprint(max_chars=500) != chunking_fingerprint(max_chars=200)


def test_manifest_ordering_and_resume_skip(tmp_path: Path) -> None:
    book = ensure_book_work_dir(tmp_path / "out", "abc123")
    chunks = partition_text("One. Two. Three.", max_chars=8, id_prefix="c")
    manifest = create_manifest("abc123", chunks)
    # Complete first chunk with a real wav stub.
    wav = book.audio_dir / "chunk-000000.wav"
    wav.write_bytes(b"RIFF....WAVE")
    mark_completed(manifest, chunks[0].id, wav.relative_to(book.root))
    save_manifest(manifest, book.manifest_path)

    loaded = load_manifest(book.manifest_path)
    pending = pending_chunks(loaded, book_root=book.root)
    assert chunks[0].id not in {p.id for p in pending}
    assert {p.id for p in pending} == {c.id for c in chunks[1:]}

    ordered = loaded.ordered_chunks()
    assert [e.sequence for e in ordered] == sorted(e.sequence for e in ordered)


def test_invalid_completed_chunk_regenerated(tmp_path: Path) -> None:
    book = ensure_book_work_dir(tmp_path / "out", "abc123")
    chunks = partition_text("Hello world again today.", max_chars=10)
    manifest = create_manifest("abc123", chunks)
    mark_completed(manifest, chunks[0].id, "audio/missing.wav")
    assert not is_chunk_valid(manifest.chunks[0], book_root=book.root)
    pending = pending_chunks(manifest, book_root=book.root)
    assert chunks[0].id in {p.id for p in pending}
    assert manifest.get(chunks[0].id).status is ChunkStatus.PENDING


def test_fingerprint_mismatch_invalidates_all(tmp_path: Path) -> None:
    book = ensure_book_work_dir(tmp_path / "out", "abc123")
    chunks = partition_text("Hello there friend.", max_chars=50)
    fp_old = chunking_fingerprint(max_chars=50)
    manifest = create_manifest("abc123", chunks, fingerprint=fp_old)
    wav = book.audio_dir / "chunk-000000.wav"
    wav.write_bytes(b"RIFF")
    mark_completed(manifest, chunks[0].id, wav.relative_to(book.root))

    pending = pending_chunks(
        manifest,
        book_root=book.root,
        current_fingerprint=chunking_fingerprint(max_chars=20),
    )
    assert len(pending) == len(chunks)


def test_book_id_from_content_not_output_path(tmp_path: Path) -> None:
    src = tmp_path / "book.pdf"
    src.write_bytes(b"%PDF-content-xyz")
    renamed = tmp_path / "renamed.pdf"
    renamed.write_bytes(src.read_bytes())
    assert compute_book_id(src) == compute_book_id(renamed)

    out_a = tmp_path / "out-a"
    out_b = tmp_path / "elsewhere" / "out-b"
    book_id = compute_book_id(src)
    layout_a = ensure_book_work_dir(out_a, book_id)
    layout_b = ensure_book_work_dir(out_b, book_id)
    assert layout_a.book_id == layout_b.book_id == book_id
    assert layout_a.root.name == book_id
    assert "audiobook.m4b" not in str(layout_a.root)
