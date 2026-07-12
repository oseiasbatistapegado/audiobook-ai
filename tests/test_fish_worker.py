"""Fish worker job loop with fake TTS / guardian (no real GPU)."""

from __future__ import annotations

from pathlib import Path

from audiobook_ai.gpu.guardian import GuardianConfig, VRAMGuardian
from audiobook_ai.gpu.jobs import (
    JobConfig,
    JobDefinition,
    WorkerExitCode,
    read_result,
    write_job,
)
from audiobook_ai.gpu.memory import VRAMSnapshot
from audiobook_ai.models.audio import AudioSegment
from audiobook_ai.models.speech import partition_text
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.state.manifest import create_manifest, load_manifest, save_manifest
from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.utils.workdir import ensure_book_work_dir
from audiobook_ai.workers.fish_speech import run_fish_speech_job


class FakeProvider:
    def __init__(self, free_mib: float) -> None:
        self.free_mib = free_mib
        self.history: list[float] = []

    def snapshot(self) -> VRAMSnapshot:
        self.history.append(self.free_mib)
        return VRAMSnapshot(total_mib=24576.0, free_mib=self.free_mib)


class FakeTTS(TTSBackend):
    def __init__(self) -> None:
        self.texts: list[str] = []

    def release(self) -> None:
        pass

    def synthesize(self, request: TTSRequest) -> AudioSegment:
        self.texts.append(request.text)
        return AudioSegment(data=b"RIFFWAV", format="wav")

    def ensure_ready(self, **kwargs: object) -> None:
        return None


def test_fish_worker_persists_before_next_chunk(tmp_path: Path) -> None:
    book = ensure_book_work_dir(tmp_path / "out", "bookid01")
    chunks = partition_text("Alpha. Beta. Gamma.", max_chars=8)
    for i, chunk in enumerate(chunks):
        chunk.metadata = {
            "chapter_id": "ch-1",
            "voice_id": "narrator",
            "emotion": "neutral",
        }
        chunk.id = f"ch-1-{i:06d}"
        chunk.sequence = i
    manifest = create_manifest("bookid01", chunks)
    save_manifest(manifest, book.manifest_path)

    job_directory = book.jobs_dir / "fish-test"
    job_directory.mkdir()
    write_job(
        job_directory,
        JobDefinition(
            job_id="fish-test",
            backend="fish-speech",
            book_id="bookid01",
            book_root=str(book.root),
            manifest_path=str(book.manifest_path),
            pending_chunk_ids=[c.id for c in chunks],
            config=JobConfig(
                before_load_target_mib=1000,
                before_chunk_target_mib=500,
                fish_chunks_per_worker=0,
            ),
        ),
    )

    provider = FakeProvider(5000.0)
    guardian = VRAMGuardian(
        provider,
        cfg=GuardianConfig(
            hard_floor_mib=300,
            before_chunk_target_mib=500,
            load_targets_mib={"fish-speech": 1000, "parler": 500},
            progressive_window_k=3,
            progressive_drop_mib=256,
        ),
    )
    tts = FakeTTS()
    code = run_fish_speech_job(job_directory, tts=tts, guardian=guardian)
    assert code == int(WorkerExitCode.SUCCESS)
    assert len(tts.texts) == len(chunks)

    loaded = load_manifest(book.manifest_path)
    for entry in loaded.ordered_chunks():
        assert entry.status.value == "completed"
        assert entry.audio_path is not None
        assert (book.root / entry.audio_path).is_file()

    result = read_result(job_directory)
    assert result is not None
    assert result.exit_code == int(WorkerExitCode.SUCCESS)
    assert result.restart_reason is None


def test_fish_worker_no_residency_restart_when_cap_disabled(tmp_path: Path) -> None:
    """Guardian-stable + cap 0 → >2 chunks without restart_reason=residency."""
    book = ensure_book_work_dir(tmp_path / "out", "bookid04")
    chunks = partition_text("One. Two. Three. Four. Five.", max_chars=5)
    assert len(chunks) > 2
    for i, chunk in enumerate(chunks):
        chunk.metadata = {
            "chapter_id": "ch-1",
            "voice_id": "narrator",
            "emotion": "neutral",
        }
        chunk.id = f"ch-1-{i:06d}"
        chunk.sequence = i
    save_manifest(create_manifest("bookid04", chunks), book.manifest_path)

    job_directory = book.jobs_dir / "fish-nocap"
    job_directory.mkdir()
    write_job(
        job_directory,
        JobDefinition(
            job_id="fish-nocap",
            backend="fish-speech",
            book_id="bookid04",
            book_root=str(book.root),
            manifest_path=str(book.manifest_path),
            pending_chunk_ids=[c.id for c in chunks],
            config=JobConfig(
                before_load_target_mib=100,
                before_chunk_target_mib=100,
                fish_chunks_per_worker=0,
            ),
        ),
    )
    provider = FakeProvider(8000.0)
    guardian = VRAMGuardian(
        provider,
        cfg=GuardianConfig(
            hard_floor_mib=300,
            before_chunk_target_mib=100,
            load_targets_mib={"fish-speech": 100, "parler": 100},
            progressive_window_k=3,
            progressive_drop_mib=256,
        ),
    )
    code = run_fish_speech_job(job_directory, tts=FakeTTS(), guardian=guardian)
    assert code == int(WorkerExitCode.SUCCESS)
    result = read_result(job_directory)
    assert result is not None
    assert result.restart_reason is None
    assert len(result.completed_chunk_ids) == len(chunks)


def test_fish_worker_residency_cap_escape_hatch(tmp_path: Path) -> None:
    book = ensure_book_work_dir(tmp_path / "out", "bookid05")
    chunks = partition_text("One. Two. Three. Four.", max_chars=5)
    assert len(chunks) >= 3
    for i, chunk in enumerate(chunks):
        chunk.metadata = {
            "chapter_id": "ch-1",
            "voice_id": "narrator",
            "emotion": "neutral",
        }
        chunk.id = f"ch-1-{i:06d}"
        chunk.sequence = i
    save_manifest(create_manifest("bookid05", chunks), book.manifest_path)

    job_directory = book.jobs_dir / "fish-cap"
    job_directory.mkdir()
    write_job(
        job_directory,
        JobDefinition(
            job_id="fish-cap",
            backend="fish-speech",
            book_id="bookid05",
            book_root=str(book.root),
            manifest_path=str(book.manifest_path),
            pending_chunk_ids=[c.id for c in chunks],
            config=JobConfig(
                before_load_target_mib=100,
                before_chunk_target_mib=100,
                fish_chunks_per_worker=2,
            ),
        ),
    )
    provider = FakeProvider(8000.0)
    guardian = VRAMGuardian(
        provider,
        cfg=GuardianConfig(
            hard_floor_mib=300,
            before_chunk_target_mib=100,
            load_targets_mib={"fish-speech": 100, "parler": 100},
            progressive_window_k=3,
            progressive_drop_mib=256,
        ),
    )
    code = run_fish_speech_job(job_directory, tts=FakeTTS(), guardian=guardian)
    assert code == int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
    result = read_result(job_directory)
    assert result is not None
    assert result.restart_reason == "residency"
    assert len(result.completed_chunk_ids) == 2


def test_fish_worker_progressive_growth_restart(tmp_path: Path) -> None:
    book = ensure_book_work_dir(tmp_path / "out", "bookid06")
    chunks = partition_text("Aaa. Bbb. Ccc. Ddd.", max_chars=5)
    assert len(chunks) >= 3
    for i, chunk in enumerate(chunks):
        chunk.metadata = {
            "chapter_id": "ch-1",
            "voice_id": "narrator",
            "emotion": "neutral",
        }
        chunk.id = f"ch-1-{i:06d}"
        chunk.sequence = i
    save_manifest(create_manifest("bookid06", chunks), book.manifest_path)

    job_directory = book.jobs_dir / "fish-prog"
    job_directory.mkdir()
    write_job(
        job_directory,
        JobDefinition(
            job_id="fish-prog",
            backend="fish-speech",
            book_id="bookid06",
            book_root=str(book.root),
            manifest_path=str(book.manifest_path),
            pending_chunk_ids=[c.id for c in chunks],
            config=JobConfig(
                before_load_target_mib=100,
                before_chunk_target_mib=100,
                fish_chunks_per_worker=0,
                progressive_window_k=3,
                progressive_drop_mib=200,
            ),
        ),
    )

    class DroppingProvider:
        def __init__(self) -> None:
            self.free_mib = 5000.0
            self.n = 0

        def snapshot(self) -> VRAMSnapshot:
            # Decline free after each reclaim sample so progressive fires.
            self.n += 1
            if self.n > 2:
                self.free_mib = max(1000.0, self.free_mib - 150.0)
            return VRAMSnapshot(total_mib=24576.0, free_mib=self.free_mib)

    provider = DroppingProvider()
    guardian = VRAMGuardian(
        provider,
        cfg=GuardianConfig(
            hard_floor_mib=300,
            before_chunk_target_mib=100,
            load_targets_mib={"fish-speech": 100, "parler": 100},
            progressive_window_k=3,
            progressive_drop_mib=200,
        ),
    )
    code = run_fish_speech_job(job_directory, tts=FakeTTS(), guardian=guardian)
    assert code == int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
    result = read_result(job_directory)
    assert result is not None
    assert result.restart_reason == "progressive"


def test_fish_worker_controlled_restart_when_below_chunk_target(tmp_path: Path) -> None:
    book = ensure_book_work_dir(tmp_path / "out", "bookid02")
    chunks = partition_text("Only one chunk text here.", max_chars=500)
    chunks[0].metadata = {
        "chapter_id": "ch-1",
        "voice_id": "narrator",
        "emotion": "neutral",
    }
    save_manifest(create_manifest("bookid02", chunks), book.manifest_path)

    job_directory = book.jobs_dir / "fish-low"
    job_directory.mkdir()
    write_job(
        job_directory,
        JobDefinition(
            job_id="fish-low",
            backend="fish-speech",
            book_id="bookid02",
            book_root=str(book.root),
            manifest_path=str(book.manifest_path),
            pending_chunk_ids=[chunks[0].id],
            config=JobConfig(before_load_target_mib=100, before_chunk_target_mib=4000),
        ),
    )

    # Enough for load gate (100) but not chunk target (4000).
    provider = FakeProvider(500.0)
    guardian = VRAMGuardian(
        provider,
        cfg=GuardianConfig(
            hard_floor_mib=300,
            before_chunk_target_mib=4000,
            load_targets_mib={"fish-speech": 100, "parler": 100},
        ),
    )
    code = run_fish_speech_job(job_directory, tts=FakeTTS(), guardian=guardian)
    assert code == int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
    result = read_result(job_directory)
    assert result is not None
    assert "chunk gate" in (result.message or "")
    assert result.restart_reason == "headroom"


class OomTTS(TTSBackend):
    def release(self) -> None:
        pass

    def ensure_ready(self, **kwargs: object) -> None:
        return None

    def synthesize(self, request: TTSRequest) -> AudioSegment:
        raise RuntimeError(
            "HIP out of memory. Tried to allocate 210.00 MiB. "
            "GPU 0 has a total capacity of 23.98 GiB of which 1016.50 MiB is free."
        )


def test_fish_worker_oom_is_reclaim_only_no_failed_chunk_id(tmp_path: Path) -> None:
    """Unexpected OOM must not burn per-chunk attempts via failed_chunk_id."""
    book = ensure_book_work_dir(tmp_path / "out", "bookid03")
    chunks = partition_text("Texto curto para OOM.", max_chars=500)
    chunks[0].metadata = {
        "chapter_id": "ch-1",
        "voice_id": "narrator",
        "emotion": "neutral",
    }
    save_manifest(create_manifest("bookid03", chunks), book.manifest_path)

    job_directory = book.jobs_dir / "fish-oom"
    job_directory.mkdir()
    write_job(
        job_directory,
        JobDefinition(
            job_id="fish-oom",
            backend="fish-speech",
            book_id="bookid03",
            book_root=str(book.root),
            manifest_path=str(book.manifest_path),
            pending_chunk_ids=[chunks[0].id],
            config=JobConfig(before_load_target_mib=100, before_chunk_target_mib=100),
        ),
    )

    provider = FakeProvider(5000.0)
    guardian = VRAMGuardian(
        provider,
        cfg=GuardianConfig(
            hard_floor_mib=300,
            before_chunk_target_mib=100,
            load_targets_mib={"fish-speech": 100, "parler": 100},
        ),
    )
    code = run_fish_speech_job(job_directory, tts=OomTTS(), guardian=guardian)
    assert code == int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
    result = read_result(job_directory)
    assert result is not None
    assert result.failed_chunk_id is None
    assert result.restart_reason == "oom"
    assert result.oom_chunk_id == chunks[0].id
    assert "unexpected_oom" in (result.message or "")

    loaded = load_manifest(book.manifest_path)
    entry = loaded.get(chunks[0].id)
    assert entry is not None
    assert entry.status.value == "pending"
    assert entry.attempts == 0
