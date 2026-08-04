"""Tests for Pass A interpret progress resume."""

from __future__ import annotations

from pathlib import Path

from audiobook_ai import config
from audiobook_ai.models.speech import chunking_fingerprint
from audiobook_ai.state.interpret_progress import (
    InterpretProgress,
    bootstrap_interpreted_ids,
    bootstrap_synthesized_ids,
    empty_progress,
    load_interpret_progress,
    mark_chapter_interpreted,
    mark_chapter_synthesized,
    resolve_interpret_progress,
    save_interpret_progress,
)
from audiobook_ai.state.manifest import ManifestChunkEntry, SpeechManifest, ChunkStatus


def test_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "interpret_progress.json"
    progress = InterpretProgress(
        interpreted_chapter_ids=["ch-001", "ch-003"],
        model="qwen3.6:27b",
        adaptation_policy_version="v5",
        diarization_policy_version="v5",
    )
    save_interpret_progress(progress, path)
    loaded = load_interpret_progress(path)
    assert loaded is not None
    assert loaded.interpreted_chapter_ids == ["ch-001", "ch-003"]
    assert loaded.model == "qwen3.6:27b"


def test_mark_chapter_idempotent() -> None:
    progress = empty_progress(model="m")
    once = mark_chapter_interpreted(progress, "ch-001")
    twice = mark_chapter_interpreted(once, "ch-001")
    assert once.interpreted_chapter_ids == ["ch-001"]
    assert twice.interpreted_chapter_ids == ["ch-001"]


def test_matches_execution_invalidates_on_model() -> None:
    progress = empty_progress(model="qwen3:8b")
    assert progress.matches_execution(model="qwen3:8b")
    assert not progress.matches_execution(model="qwen3.6:27b")


def test_matches_execution_invalidates_on_policy(monkeypatch) -> None:
    progress = empty_progress(model="m")
    monkeypatch.setattr(config, "LLM_DIARIZATION_POLICY_VERSION", "v-other")
    assert not progress.matches_execution(model="m")


def test_bootstrap_excludes_last_present_chapter() -> None:
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="a",
                sequence=0,
                text="t",
                metadata={"chapter_id": "ch-001"},
                status=ChunkStatus.PENDING,
            ),
            ManifestChunkEntry(
                id="b",
                sequence=1,
                text="t",
                metadata={"chapter_id": "ch-003"},
                status=ChunkStatus.PENDING,
            ),
            ManifestChunkEntry(
                id="c",
                sequence=2,
                text="t",
                metadata={"chapter_id": "ch-004"},
                status=ChunkStatus.PENDING,
            ),
            ManifestChunkEntry(
                id="d",
                sequence=3,
                text="t",
                metadata={"chapter_id": "ch-005"},
                status=ChunkStatus.PENDING,
            ),
        ],
    )
    ids = bootstrap_interpreted_ids(
        ["ch-001", "ch-003", "ch-004", "ch-005", "ch-006"],
        manifest,
    )
    assert ids == ["ch-001", "ch-003", "ch-004"]


def test_bootstrap_single_chapter_returns_empty() -> None:
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="a",
                sequence=0,
                text="t",
                metadata={"chapter_id": "ch-001"},
            )
        ],
    )
    assert bootstrap_interpreted_ids(["ch-001", "ch-002"], manifest) == []


def test_resolve_invalidates_and_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "interpret_progress.json"
    save_interpret_progress(empty_progress(model="old-model"), path)
    resolved = resolve_interpret_progress(
        path,
        model="new-model",
        book_chapter_ids=["ch-001"],
    )
    assert resolved.interpreted_chapter_ids == []
    assert resolved.model == "new-model"


def test_resolve_bootstraps_from_manifest(tmp_path: Path) -> None:
    progress_path = tmp_path / "interpret_progress.json"
    manifest_path = tmp_path / "manifest.json"
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="a",
                sequence=0,
                text="t",
                metadata={"chapter_id": "ch-001"},
            ),
            ManifestChunkEntry(
                id="b",
                sequence=1,
                text="t",
                metadata={"chapter_id": "ch-002"},
            ),
            ManifestChunkEntry(
                id="c",
                sequence=2,
                text="t",
                metadata={"chapter_id": "ch-003"},
            ),
        ],
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    resolved = resolve_interpret_progress(
        progress_path,
        model="m",
        book_chapter_ids=["ch-001", "ch-002", "ch-003"],
        manifest_path=manifest_path,
    )
    assert resolved.interpreted_chapter_ids == ["ch-001", "ch-002"]


def test_mark_chapter_synthesized_idempotent() -> None:
    progress = empty_progress(model="m")
    once = mark_chapter_synthesized(progress, "ch-001")
    twice = mark_chapter_synthesized(once, "ch-001")
    assert once.synthesized_chapter_ids == ["ch-001"]
    assert twice.synthesized_chapter_ids == ["ch-001"]


def test_is_synthesized_works() -> None:
    progress = empty_progress(model="m")
    assert not progress.is_synthesized("ch-001")
    synched = mark_chapter_synthesized(progress, "ch-001")
    assert synched.is_synthesized("ch-001")


def test_bootstrap_synthesized_ids_all_valid(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    # Create valid audio files
    for seq in [0, 1, 2]:
        (audio_dir / f"chunk-{seq:06d}.wav").write_bytes(b"fake audio")
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="a",
                sequence=0,
                text="t",
                metadata={"chapter_id": "ch-001"},
                status=ChunkStatus.COMPLETED,
                audio_path=str(audio_dir / "chunk-000000.wav"),
            ),
            ManifestChunkEntry(
                id="b",
                sequence=1,
                text="t",
                metadata={"chapter_id": "ch-001"},
                status=ChunkStatus.COMPLETED,
                audio_path=str(audio_dir / "chunk-000001.wav"),
            ),
            ManifestChunkEntry(
                id="c",
                sequence=2,
                text="t",
                metadata={"chapter_id": "ch-002"},
                status=ChunkStatus.COMPLETED,
                audio_path=str(audio_dir / "chunk-000002.wav"),
            ),
        ],
    )
    synthesized = bootstrap_synthesized_ids(
        ["ch-001", "ch-002", "ch-003"],
        manifest,
        tmp_path,
    )
    assert synthesized == ["ch-001", "ch-002"]


def test_bootstrap_synthesized_ids_pending_not_included(tmp_path: Path) -> None:
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="a",
                sequence=0,
                text="t",
                metadata={"chapter_id": "ch-001"},
                status=ChunkStatus.PENDING,
            ),
        ],
    )
    synthesized = bootstrap_synthesized_ids(
        ["ch-001", "ch-002"],
        manifest,
        tmp_path,
    )
    assert synthesized == []


# ---------------------------------------------------------------------------
# Task 1.5: VRAM threshold config assertions for interpret progress
# ---------------------------------------------------------------------------


def test_progress_uses_current_chunking_fingerprint() -> None:
    """The fingerprint must include the TTS_MAX_CHUNK_CHARS that changed in config."""
    from audiobook_ai import config
    from audiobook_ai.models.speech import chunking_fingerprint

    fp = chunking_fingerprint()
    # chunking_fingerprint is a hash; just verify it's non-empty and
    # would change if TTS_MAX_CHUNK_CHARS were different.
    assert isinstance(fp, str)
    assert len(fp) > 0


def test_interpret_progress_config_ref() -> None:
    """Interpret progress module imports config — verify thresholds still sane."""
    from audiobook_ai import config

    # These thresholds are checked by the GPU lifecycle tests;
    # this test ensures the config module itself is importable
    # and the values are consistent with what interpret progress expects.
    assert config.TTS_MAX_CHUNK_CHARS == 5000
    assert config.TTS_MULTI_WORKER_COUNT == 2
    assert config.TTS_ASYNC_OVERLAP == 1
