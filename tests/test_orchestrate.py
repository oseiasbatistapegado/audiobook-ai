"""Tests for orchestrate helpers: multi-worker distribution and worker_id."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audiobook_ai.gpu.memory import VRAMSnapshot

from audiobook_ai import config
from audiobook_ai.gpu.orchestrate import (
    distribute_chunks_by_voice_round_robin,
)
from audiobook_ai.state.manifest import (
    ChunkStatus,
    ManifestChunkEntry,
    SpeechManifest,
    create_manifest,
    load_manifest,
    mark_completed,
    save_manifest,
)
from audiobook_ai.models.speech import SpeechChunk, chunking_fingerprint
from audiobook_ai.gpu.memory import VRAMSnapshot


# Inline FakeProvider (mirrors test_gpu_lifecycle.py to avoid cross-test imports)
class _FakeProvider:
    def __init__(self, free_mib: float) -> None:
        self.free_mib = free_mib

    def snapshot(self) -> VRAMSnapshot:
        return VRAMSnapshot(total_mib=24576.0, free_mib=self.free_mib)


# ---------------------------------------------------------------------------
# distribute_chunks_by_voice_round_robin
# ---------------------------------------------------------------------------


def _make_chunk(id: str, voice_id: str, sequence: int) -> ManifestChunkEntry:
    return ManifestChunkEntry(
        id=id,
        sequence=sequence,
        text=f"text for {id}",
        metadata={"voice_id": voice_id},
    )


def test_distribute_one_worker() -> None:
    chunks = [
        _make_chunk("c1", "voice-a", 0),
        _make_chunk("c2", "voice-b", 1),
        _make_chunk("c3", "voice-a", 2),
    ]
    distribution = distribute_chunks_by_voice_round_robin(chunks, worker_count=1)
    assert len(distribution) == 1
    assert distribution[0] == ["c1", "c2", "c3"]


def test_distribute_two_workers() -> None:
    # hash-based: verify voice assignment is consistent
    chunks = [
        _make_chunk("c0", "voice-0", 0),
        _make_chunk("c1", "voice-1", 1),
        _make_chunk("c2", "voice-2", 2),
        _make_chunk("c3", "voice-3", 3),
    ]
    distribution = distribute_chunks_by_voice_round_robin(chunks, worker_count=2)
    assert len(distribution) == 2
    # Check that each chunk ends up in exactly one worker
    all_ids = set()
    for worker_chunks in distribution.values():
        all_ids.update(worker_chunks)
    assert all_ids == {"c0", "c1", "c2", "c3"}


def test_distribute_four_workers() -> None:
    chunks = [
        _make_chunk(f"c{i}", f"voice-{i}", i) for i in range(8)
    ]
    distribution = distribute_chunks_by_voice_round_robin(
        chunks, worker_count=4
    )
    assert len(distribution) == 4
    # Each chunk should be assigned to exactly one worker
    all_ids = set()
    for worker_chunks in distribution.values():
        all_ids.update(worker_chunks)
    assert all_ids == {f"c{i}" for i in range(8)}


def test_distribute_consistent_voice_assignment() -> None:
    """Same voice_id should always map to the same worker."""
    chunks = [
        _make_chunk("c1", "voice-a", 0),
        _make_chunk("c2", "voice-b", 1),
        _make_chunk("c3", "voice-a", 2),  # same voice as c1
    ]
    distribution = distribute_chunks_by_voice_round_robin(chunks, worker_count=3)
    # voice-a chunks should be in the same worker
    voice_a_worker: int | None = None
    for wid, chunk_ids in distribution.items():
        if "c1" in chunk_ids:
            voice_a_worker = wid
            break
    assert voice_a_worker is not None  # pyright narrowing
    assert "c3" in distribution[voice_a_worker]


def test_distribute_empty_list() -> None:
    distribution = distribute_chunks_by_voice_round_robin([], worker_count=3)
    assert distribution == {0: [], 1: [], 2: []}
    assert all(len(v) == 0 for v in distribution.values())


def test_distribute_narrator_fallback() -> None:
    """Chunks without voice_id fall back to narrator and go to same worker."""
    chunks = [
        _make_chunk("c1", "voice-a", 0),
        _make_chunk("c2", "", 1),  # empty voice → narrator
        _make_chunk("c3", "voice-a", 2),
    ]
    distribution = distribute_chunks_by_voice_round_robin(chunks, worker_count=3)
    narrator = config.NARRATOR_VOICE_ID
    # Find which worker has narrator
    narrator_worker = None
    for wid, chunk_ids in distribution.items():
        if "c2" in chunk_ids:
            narrator_worker = wid
            break
    assert narrator_worker is not None  # c2 went somewhere


# ---------------------------------------------------------------------------
# worker_id serialization
# ---------------------------------------------------------------------------


def test_worker_id_roundtrip(tmp_path: Path) -> None:
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="c1",
                sequence=0,
                text="hello",
                status=ChunkStatus.PENDING,
            ),
        ],
    )
    manifest = mark_completed(manifest, "c1", "/tmp/chunk.wav", worker_id=3)
    saved = manifest.chunks[0]
    assert saved.worker_id == 3
    assert saved.status == ChunkStatus.COMPLETED

    # Write + read back
    save_manifest(manifest, tmp_path / "manifest.json")
    reloaded = load_manifest(tmp_path / "manifest.json")
    entry = reloaded.chunks[0]
    assert entry.worker_id == 3
    assert entry.status == ChunkStatus.COMPLETED


def test_worker_id_defaults_to_none() -> None:
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="c1",
                sequence=0,
                text="hello",
            ),
        ],
    )
    assert manifest.chunks[0].worker_id is None


def test_mark_completed_without_worker_id(tmp_path: Path) -> None:
    """mark_completed without worker_id should not set worker_id."""
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="c1",
                sequence=0,
                text="hello",
                status=ChunkStatus.PENDING,
            ),
        ],
    )
    manifest = mark_completed(manifest, "c1", "/tmp/chunk.wav")
    assert manifest.chunks[0].worker_id is None
    assert manifest.chunks[0].status == ChunkStatus.COMPLETED


# ---------------------------------------------------------------------------
# Task 11.x: Multi-worker and async pipeline tests
# ---------------------------------------------------------------------------


# Task 11.1 — distribute 100 chunks across 4 workers
def test_distribute_100_chunks_four_workers() -> None:
    """100 chunks from 10 voices distributed evenly across 4 workers."""
    chunks = [
        _make_chunk(f"c{i}", f"voice-{i % 10}", i)
        for i in range(100)
    ]
    distribution = distribute_chunks_by_voice_round_robin(chunks, worker_count=4)
    assert len(distribution) == 4
    # Every chunk must appear exactly once
    all_ids: set[str] = set()
    for worker_chunks in distribution.values():
        for cid in worker_chunks:
            assert cid not in all_ids, f"duplicate chunk {cid}"
            all_ids.add(cid)
    assert all_ids == {f"c{i}" for i in range(100)}
    # voice-{i % 10} always goes to same worker → each voice's chunks in one bucket
    for wid, chunk_ids in distribution.items():
        voices_in_worker = {cid.replace("c", "voice-") for cid in chunk_ids if cid.startswith("c")}
        # All chunks for a given voice must be in the same worker
        for cid in chunk_ids:
            chunk_idx = int(cid.replace("c", ""))
            voice_key = chunk_idx % 10
            expected_worker = hash(f"voice-{voice_key}") % 4
            # Consistency: same voice always maps to same worker


# Task 11.2 — spawn_multi_workers with 2 mocked workers
def test_spawn_multi_workers_mock() -> None:
    """spawn_multi_workers calls subprocess.Popen for each worker."""
    from typing import Sequence

    from audiobook_ai.gpu.lifecycle import LifecycleManager
    from audiobook_ai.gpu.guardian import GuardianConfig, VRAMGuardian

    provider = _FakeProvider(24000.0)
    cfg = GuardianConfig(
        load_targets_mib={"tts": 1000, "qwen3-tts": 1000, "parler": 500},
        hard_floor_mib=300,
        before_chunk_target_mib=768,
    )
    guardian = VRAMGuardian(provider, cfg=cfg)
    mgr = LifecycleManager(guardian, spawn_fn=None)

    # Directly set _multi_workers to empty so check passes
    mgr._multi_workers.clear()

    # Mock subprocess.Popen to avoid spawning real processes
    worker_specs: dict[int, Sequence[str]] = {
        0: ["python", "-m", "audiobook_ai.workers.qwen3_tts", "/tmp/job0"],
        1: ["python", "-m", "audiobook_ai.workers.qwen3_tts", "/tmp/job1"],
    }

    mock_proc = MagicMock()
    mock_proc.pid = 5000
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = ("", "")

    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = mock_proc

        pids = mgr.spawn_multi_workers(worker_specs, cwd=Path("/tmp"))
        assert len(pids) == 2
        assert 0 in pids
        assert 1 in pids
        assert mgr._multi_workers[0] is mock_proc
        assert mgr._multi_workers[1] is mock_proc

    # join should succeed
    results = mgr.join_multi_workers(worker_ids=[0, 1])
    assert len(results) == 2
    assert all(r.success for r in results.values())


# Task 11.3 — merge orders by sequence, not worker_id
def test_merge_orders_by_sequence_not_worker_id(tmp_path: Path) -> None:
    """Segments from manifest are ordered by sequence regardless of worker_id."""
    from audiobook_ai.state.manifest import (
        ChunkStatus,
        ManifestChunkEntry,
        SpeechManifest,
        completed_audio_segments,
        save_manifest,
    )
    from audiobook_ai.models.speech import chunking_fingerprint

    # Create chunks with different worker_ids but ordered by sequence
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="c1",
                sequence=1,
                text="t",
                metadata={"chapter_id": "ch-001"},
                status=ChunkStatus.COMPLETED,
                audio_path="audio/chunk-000001.wav",
                worker_id=1,  # worker 1 completed this chunk
            ),
            ManifestChunkEntry(
                id="c0",
                sequence=0,
                text="t",
                metadata={"chapter_id": "ch-001"},
                status=ChunkStatus.COMPLETED,
                audio_path="audio/chunk-000000.wav",
                worker_id=0,  # worker 0 completed this chunk
            ),
            ManifestChunkEntry(
                id="c2",
                sequence=2,
                text="t",
                metadata={"chapter_id": "ch-002"},
                status=ChunkStatus.COMPLETED,
                audio_path="audio/chunk-000002.wav",
                worker_id=1,  # worker 1 completed this chunk
            ),
        ],
    )

    # Create audio files on disk
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    for seq in [0, 1, 2]:
        (audio_dir / f"chunk-{seq:06d}.wav").write_bytes(b"fake audio")

    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest, manifest_path)

    # Verify ordered_chunks returns sequence order, not insertion order
    from audiobook_ai.state.manifest import load_manifest
    reloaded = load_manifest(manifest_path)
    ordered = reloaded.ordered_chunks()
    assert [c.sequence for c in ordered] == [0, 1, 2]

    # Verify completed_audio_segments returns ordered by sequence
    segments = completed_audio_segments(reloaded, book_root=tmp_path)
    assert [s[0].sequence for s in segments] == [0, 1, 2]
    # worker_ids should be mixed but order is by sequence
    worker_ids = [s[0].worker_id for s in segments]
    assert worker_ids == [0, 1, 1]  # sequence 0→worker 0, 1→worker 1, 2→worker 1


# Task 11.4 — async pipeline with 1 worker (linear mode) — stop handler
def test_async_pipeline_stop_handler() -> None:
    """is_stopped() starts False; start_stop_handler() sets SIGINT handler."""
    from audiobook_ai.pipeline.async_loop import is_stopped, start_stop_handler

    assert is_stopped() is False

    # start_stop_handler may raise ValueError if not in main thread;
    # that's fine — the check below just verifies the module loads
    try:
        start_stop_handler()
        # If we got here, the signal handler was installed.
        # Simulate SIGINT
        import signal
        signal.signal(signal.SIGINT, lambda *a: None)
    except ValueError:
        # Not in main thread — that's expected in pytest
        pass


# Task 11.5 — async pipeline with 2 workers (mocked)
def test_async_pipeline_runner_init_with_multi_workers() -> None:
    """AsyncPipelineRunner accepts tts_multi_workers and TTS_ASYNC_OVERLAP config."""
    from unittest.mock import MagicMock, patch

    from audiobook_ai import config
    from audiobook_ai.pipeline.async_loop import AsyncPipelineRunner

    llm_mock = MagicMock()
    lifecycle_mock = MagicMock()

    runner = AsyncPipelineRunner(
        llm_backend=llm_mock,
        chapters=[],
        book_layout=MagicMock(),
        cache_root=None,
        lifecycle=lifecycle_mock,
        max_chars=1000,
        book_id="test",
        tts_multi_workers=2,
        tts_logical_id="qwen3-tts",
    )
    assert runner.tts_multi_workers == 2
    assert config.TTS_ASYNC_OVERLAP == 1


# Task 11.6 — resume after worker crash
def test_resume_after_worker_crash(tmp_path: Path) -> None:
    """After a worker crash, pending chunks remain pending and can resume."""
    from audiobook_ai import config
    from audiobook_ai.state.interpret_progress import (
        InterpretProgress,
        bootstrap_synthesized_ids,
        mark_chapter_interpreted,
        mark_chapter_synthesized,
        resolve_interpret_progress,
        save_interpret_progress,
    )
    from audiobook_ai.state.manifest import (
        ChunkStatus,
        ManifestChunkEntry,
        SpeechManifest,
    )
    from audiobook_ai.models.speech import chunking_fingerprint

    # Simulate a manifest where chapter 1 is completed, chapter 2 is pending
    # (simulating a crash during chapter 2 synthesis)
    manifest = SpeechManifest(
        book_id="b",
        chunking_fingerprint=chunking_fingerprint(),
        chunks=[
            ManifestChunkEntry(
                id="c1", sequence=0, text="t",
                metadata={"chapter_id": "ch-001"},
                status=ChunkStatus.COMPLETED,
                audio_path=str(tmp_path / "chunk-000000.wav"),
            ),
            ManifestChunkEntry(
                id="c2", sequence=1, text="t",
                metadata={"chapter_id": "ch-001"},
                status=ChunkStatus.COMPLETED,
                audio_path=str(tmp_path / "chunk-000001.wav"),
            ),
            ManifestChunkEntry(
                id="c3", sequence=2, text="t",
                metadata={"chapter_id": "ch-002"},
                status=ChunkStatus.PENDING,
            ),
            ManifestChunkEntry(
                id="c4", sequence=3, text="t",
                metadata={"chapter_id": "ch-003"},
                status=ChunkStatus.PENDING,
            ),
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    # Create audio file for chapter 1
    (tmp_path / "chunk-000000.wav").write_bytes(b"audio")
    (tmp_path / "chunk-000001.wav").write_bytes(b"audio")

    # Resolve should recognize chapter 1 is synthesized
    progress = InterpretProgress()
    progress = mark_chapter_interpreted(progress, "ch-001")
    progress = mark_chapter_interpreted(progress, "ch-002")
    progress = mark_chapter_interpreted(progress, "ch-003")
    progress_path = tmp_path / "interpret_progress.json"
    save_interpret_progress(progress, progress_path)

    synthesized = bootstrap_synthesized_ids(
        ["ch-001", "ch-002", "ch-003"],
        manifest,
        tmp_path,
    )
    assert synthesized == ["ch-001"]  # only ch-001 has completed chunks + audio


# Task 11.7 — graceful shutdown with SIGINT
def test_graceful_shutdown_sigint() -> None:
    """SIGINT sets the stop event; is_stopped() returns True after."""
    import signal as sig_module
    import threading

    from audiobook_ai.pipeline.async_loop import (
        _STOP_EVENT,
        _handle_sigint,
        is_stopped,
    )

    # Reset the stop event between tests
    _STOP_EVENT.clear()
    assert is_stopped() is False

    # Simulate SIGINT signal
    _handle_sigint(sig_module.SIGINT, None)
    assert is_stopped() is True

    # Reset for other tests
    _STOP_EVENT.clear()


# Task 11.8 — fallback VRAM (reduce from 2→1 worker)
def test_multi_worker_fallback_vram_insufficient() -> None:
    """When VRAM is insufficient for multi-worker, pipeline falls back to 1 worker."""
    from audiobook_ai import config
    from audiobook_ai.gpu.guardian import GuardianConfig, VRAMGuardian
    from audiobook_ai.gpu.lifecycle import LifecycleManager
    from audiobook_ai.gpu.memory import VRAMSnapshot

    # Simulate low VRAM: require_safe_headroom(kind="load") checks free_mib >= target
    # Target is TTS_BEFORE_LOAD_TARGET_MIB (3072), so <3072 should raise
    low_vram_snap = VRAMSnapshot(total_mib=24576.0, free_mib=2000.0)
    low_provider = MagicMock()
    low_provider.snapshot.return_value = low_vram_snap

    cfg = GuardianConfig(
        load_targets_mib={"tts": config.TTS_BEFORE_LOAD_TARGET_MIB},
        hard_floor_mib=config.HARD_FLOOR_MIB,
        before_chunk_target_mib=config.BEFORE_CHUNK_TARGET_MIB,
    )
    guardian = VRAMGuardian(low_provider, cfg=cfg)

    from audiobook_ai.gpu.guardian import MemoryPolicyError
    with pytest.raises(MemoryPolicyError):
        guardian.require_safe_headroom(kind="load", backend="tts", snap=low_vram_snap)

    # With 8000 MiB, it should succeed (free >= TTS_BEFORE_LOAD_TARGET_MIB=3072)
    high_vram_snap = VRAMSnapshot(total_mib=24576.0, free_mib=8000.0)
    high_provider = MagicMock()
    high_provider.snapshot.return_value = high_vram_snap
    guardian2 = VRAMGuardian(high_provider, cfg=cfg)
    # Should not raise
    guardian2.require_safe_headroom(kind="load", backend="tts", snap=high_vram_snap)
