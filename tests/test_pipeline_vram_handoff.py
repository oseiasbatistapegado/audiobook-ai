"""Pipeline VRAM handoff orchestration tests (mocked extract/TTS/LLM/merge)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.models.audio import AudioSegment
from audiobook_ai.models.book import Chapter, ExtractedPage, ExtractedPdf
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.llm import LLMChapterResponse, StoryUpdates
from audiobook_ai.models.story import StoryState
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.models.voice import CharacterProfile, GeneratedVoice, VoiceProfile
from audiobook_ai.pipeline import run_generate
from audiobook_ai.tts.base import TTSBackend


def _valid_wav_bytes() -> bytes:
    """Return a minimal but ffmpeg-parseable WAV file (16-bit PCM, 1s, 8kHz)."""
    import struct

    sample_rate = 8000
    num_samples = sample_rate  # 1 second
    num_channels = 1
    bits_per_sample = 16
    data = b"\\x00\\x00" * num_samples  # silence
    data_size = len(data)
    file_size = 36 + data_size  # RIFF header overhead minus 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH",
        b"RIFF",
        file_size,
        b"WAVE",
        b"fmt ",
        16,  # fmt chunk size
        1,  # PCM
        num_channels,
        sample_rate,
        sample_rate * num_channels * bits_per_sample // 8,
        num_channels * bits_per_sample // 8,
        bits_per_sample,
    )
    header += b"data" + struct.pack("<I", data_size)
    return header + data


def _fake_segment_path(
    book_root: Path,
    chapter_id: str,
    segment_index: int,
) -> Path:
    """Create a tiny WAV file and return its path."""
    audio_dir = book_root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"chunk-{segment_index:06d}.wav"
    if not path.is_file():
        path.write_bytes(_valid_wav_bytes())
    return path


class RecordingTTS(TTSBackend):
    def __init__(self) -> None:
        self.events: list[str] = []
        self.synthesize_count = 0

    def release(self) -> None:
        self.events.append("release")

    def synthesize(self, request: TTSRequest) -> AudioSegment:
        self.events.append(f"synthesize:{request.segment_index}")
        self.synthesize_count += 1
        return AudioSegment(
            data=_valid_wav_bytes(),
            format="wav",
            chapter_id=request.chapter_id,
            segment_index=request.segment_index,
        )


class RecordingLLM(LLMBackend):
    def __init__(self, *, dialogues_per_chapter: int = 2, use_remote: bool = True) -> None:
        self.events: list[str] = []
        self.dialogues_per_chapter = dialogues_per_chapter
        self.last_used_remote = False
        self._use_remote = use_remote

    def interpret_chapter(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> LLMChapterResponse:
        del story_state
        self.events.append(f"interpret:{chapter.id}")
        self.last_used_remote = self._use_remote
        dialogues = [
            Dialogue(
                speaker_name="Narrator",
                emotion=Emotion.NEUTRAL,
                text=f"Line {i} of {chapter.id}",
            )
            for i in range(self.dialogues_per_chapter)
        ]
        return LLMChapterResponse(dialogues=dialogues, story_updates=StoryUpdates())

    def unload(self) -> None:
        self.events.append("unload")


class StubVoiceGenerator:
    """Writes stub reference files without loading Parler/torch."""

    def generate_voice(
        self,
        character: CharacterProfile,
        *,
        book_id: str,
        language: str = "pt-BR",
    ) -> GeneratedVoice:
        root = Path("/tmp") / "audiobook-ai-test-voices" / book_id / character.character_id
        root.mkdir(parents=True, exist_ok=True)
        wav = root / "reference.wav"
        txt = root / "reference.txt"
        wav.write_bytes(b"RIFF....WAVE")
        txt.write_text("olá stub\n", encoding="utf-8")
        return GeneratedVoice(
            voice_id=character.character_id,
            character_id=character.character_id,
            book_id=book_id,
            language=language,
            reference_wav=wav,
            reference_text=txt,
            generator="stub",
            generator_version="1",
            model_id="stub",
            seed=1,
            voice_profile=character.voice_profile or VoiceProfile(),
        )

    def unload(self) -> None:
        return None


def _make_completed_audio_segments(
    book_root: Path,
    tts: RecordingTTS,
) -> list[tuple[Any, Path]]:
    """Build fake (entry, path) pairs from RecordingTTS events for merge.

    Each ``synthesize:<N>`` event becomes a completed segment pointing to
    a tiny WAV file written into the book's audio directory.
    """
    result: list[tuple[Any, Path]] = []
    seen: set[int] = set()
    for event in tts.events:
        if event.startswith("synthesize:"):
            seg_idx = int(event.split(":")[1])
            if seg_idx in seen:
                continue
            seen.add(seg_idx)
            path = _fake_segment_path(book_root, "", seg_idx)
            # Fake entry with minimal attributes
            entry = type(
                "FakeEntry",
                (),
                {"id": f"chunk-{seg_idx:06d}", "sequence": seg_idx},
            )()
            result.append((entry, path))
    return sorted(result, key=lambda x: x[0].sequence)  # type: ignore[arg-type,return-value]


def _mock_segments_from_manifest(book: Any, tts: RecordingTTS | None) -> list[AudioSegment]:
    """Return fake AudioSegment objects based on RecordingTTS events."""
    if tts is None:
        return []
    segments: list[AudioSegment] = []
    seen: set[int] = set()
    for event in tts.events:
        if event.startswith("synthesize:"):
            seg_idx = int(event.split(":")[1])
            if seg_idx in seen:
                continue
            seen.add(seg_idx)
            segments.append(
                AudioSegment(
                    data=b"RIFF",
                    format="wav",
                    segment_index=seg_idx,
                )
            )
    return segments


def _patched_segments_from_manifest(book: Any) -> list[AudioSegment]:
    """Standalone version for monkeypatching."""
    return []  # stub — merge is also mocked


def _make_tts_mock_and_manifest_patch(
    tts: RecordingTTS,
) -> tuple:
    """Return (mock_run_tts_phase, mock_segments_fn) for monkeypatching.

    ``mock_run_tts_phase`` writes real WAV files and updates the manifest
    so that the real ``_segments_from_manifest`` can read them back.
    """
    def mock_run_tts_phase(**kwargs):
        from audiobook_ai.state.manifest import load_manifest, save_manifest

        book = kwargs["book"]
        manifest = load_manifest(book.manifest_path)
        audio_dir = book.root / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        for entry in manifest.chunks:
            if entry.status is not None and entry.status == "completed":
                continue
            rel = f"audio/chunk-{entry.sequence:06d}.wav"
            wav_path = book.root / rel
            if not wav_path.is_file():
                wav_path.write_bytes(_valid_wav_bytes())
            entry.audio_path = rel
            entry.status = "completed"
            tts.events.append(f"synthesize:{entry.sequence}")
        save_manifest(manifest, book.manifest_path)
        return []

    def mock_segments_fn(book):
        from audiobook_ai.state.manifest import load_manifest

        manifest = load_manifest(book.manifest_path)
        segments = []
        seen = set()
        for entry in sorted(manifest.chunks, key=lambda e: e.sequence):
            if entry.sequence in seen:
                continue
            seen.add(entry.sequence)
            if entry.audio_path:
                segments.append(
                    AudioSegment(
                        data=_valid_wav_bytes(),
                        format="wav",
                        segment_index=entry.sequence,
                    )
                )
        return segments

    return mock_run_tts_phase, mock_segments_fn


def test_vram_handoff_order_per_chapter(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "out"
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    extracted = ExtractedPdf(
        title="Sample",
        pages=[
            ExtractedPage(page_number=1, text="Chapter One\n\nHello."),
            ExtractedPage(page_number=2, text="Chapter Two\n\nWorld."),
        ],
        toc=[(1, "Chapter One", 1), (1, "Chapter Two", 2)],
    )

    monkeypatch.setattr(
        "audiobook_ai.pipeline.PdfExtractor.extract",
        lambda self, path: extracted,
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.core.merge_segments",
        lambda segments, output_path, chapters_dir=None: (
            output_path.write_bytes(b"m4b"),
            output_path,
        )[1],
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.wait_until_free",
        lambda self, *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.require_safe_headroom",
        lambda self, *args, **kwargs: type("Snap", (), {"free_mib": 9999})(),
    )

    tts = RecordingTTS()
    mock_run, mock_seg = _make_tts_mock_and_manifest_patch(tts)
    monkeypatch.setattr("audiobook_ai.gpu.orchestrate.run_tts_phase", mock_run)
    monkeypatch.setattr(
        "audiobook_ai.gpu.orchestrate._segments_from_manifest",
        mock_seg,
    )

    llm = RecordingLLM(dialogues_per_chapter=2, use_remote=True)
    progress: list[tuple[str, str]] = []

    result = run_generate(
        pdf,
        work_dir=work,
        llm=llm,
        tts=tts,
        voice_generator=StubVoiceGenerator(),
        skip_preflight=True,
        tts_async_overlap=0,
        progress_callback=lambda stage, detail: progress.append((stage, detail)),
    )
    assert result.exists()

    # Two chapters interpreted; unloads batched after all chapters (voice-design + TTS).
    assert llm.events == [
        "interpret:ch-001",
        "interpret:ch-002",
        "unload",
        "unload",
    ]
    assert tts.events == [
        "synthesize:0",
        "synthesize:1",
        "synthesize:2",
        "synthesize:3",
    ]
    assert tts.synthesize_count == 4

    handoffs = [d for s, d in progress if s == "vram-handoff"]
    assert "release-tts" in handoffs
    assert "unload-llm" in handoffs
    assert "load-tts" in handoffs
    # Continuous TTS: a single load-tts for the whole pending manifest.
    assert handoffs.count("load-tts") == 1

    stages = [s for s, _ in progress]
    assert "voice-design" in stages or "tts" in stages or "interpret" in stages


def test_cache_hit_skips_unload(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "out"
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    extracted = ExtractedPdf(
        title="Sample",
        pages=[ExtractedPage(page_number=1, text="Chapter One\n\nHello.")],
        toc=[(1, "Chapter One", 1)],
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.PdfExtractor.extract",
        lambda self, path: extracted,
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.core.merge_segments",
        lambda segments, output_path, chapters_dir=None: (
            output_path.write_bytes(b"m4b"),
            output_path,
        )[1],
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.wait_until_free",
        lambda self, *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.require_safe_headroom",
        lambda self, *args, **kwargs: type("Snap", (), {"free_mib": 9999})(),
    )
    tts = RecordingTTS()
    mock_run, mock_seg = _make_tts_mock_and_manifest_patch(tts)
    monkeypatch.setattr("audiobook_ai.gpu.orchestrate.run_tts_phase", mock_run)
    monkeypatch.setattr(
        "audiobook_ai.gpu.orchestrate._segments_from_manifest",
        mock_seg,
    )
    llm = RecordingLLM(dialogues_per_chapter=1, use_remote=False)
    run_generate(
        pdf,
        work_dir=work,
        llm=llm,
        tts=tts,
        voice_generator=StubVoiceGenerator(),
        skip_preflight=True,
        tts_async_overlap=0,
    )
    # LLM stays resident after interpret (use_remote=False);
    # single unload before batched voice-design (_voice_worker=True).
    assert llm.events == ["interpret:ch-001", "unload"]


def test_interpret_resume_skips_completed_chapters(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "out"
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    extracted = ExtractedPdf(
        title="Sample",
        pages=[
            ExtractedPage(page_number=1, text="Chapter One\n\nHello."),
            ExtractedPage(page_number=2, text="Chapter Two\n\nWorld."),
        ],
        toc=[(1, "Chapter One", 1), (1, "Chapter Two", 2)],
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.PdfExtractor.extract",
        lambda self, path: extracted,
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.core.merge_segments",
        lambda segments, output_path, chapters_dir=None: (
            output_path.write_bytes(b"m4b"),
            output_path,
        )[1],
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.wait_until_free",
        lambda self, *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.require_safe_headroom",
        lambda self, *args, **kwargs: type("Snap", (), {"free_mib": 9999})(),
    )

    tts = RecordingTTS()
    mock_run, mock_seg = _make_tts_mock_and_manifest_patch(tts)
    monkeypatch.setattr("audiobook_ai.gpu.orchestrate.run_tts_phase", mock_run)
    monkeypatch.setattr(
        "audiobook_ai.gpu.orchestrate._segments_from_manifest",
        mock_seg,
    )

    llm1 = RecordingLLM(dialogues_per_chapter=1, use_remote=True)
    run_generate(
        pdf,
        work_dir=work,
        llm=llm1,
        tts=tts,
        voice_generator=StubVoiceGenerator(),
        skip_preflight=True,
        tts_async_overlap=0,
    )
    assert "interpret:ch-001" in llm1.events
    assert "interpret:ch-002" in llm1.events

    from audiobook_ai.voice.book_id import compute_book_id
    from audiobook_ai.state.manifest import load_manifest

    book_id = compute_book_id(pdf)
    manifest_path = work / book_id / "manifest.json"
    before = load_manifest(manifest_path)
    before_ids = [c.id for c in before.chunks]
    before_count = len(before.chunks)

    progress: list[tuple[str, str]] = []
    llm2 = RecordingLLM(dialogues_per_chapter=1, use_remote=True)
    run_generate(
        pdf,
        work_dir=work,
        llm=llm2,
        tts=RecordingTTS(),
        voice_generator=StubVoiceGenerator(),
        skip_preflight=True,
        tts_async_overlap=0,
        progress_callback=lambda stage, detail: progress.append((stage, detail)),
    )
    assert llm2.events == []
    assert ("interpret-skip", "ch-001") in progress
    assert ("interpret-skip", "ch-002") in progress

    after = load_manifest(manifest_path)
    assert len(after.chunks) == before_count
    assert [c.id for c in after.chunks] == before_ids


def test_no_unload_between_chapters_when_voices_already_mapped(
    tmp_path: Path, monkeypatch
) -> None:
    """After first chapter maps narrator, second remote interpret keeps LLM resident."""
    work = tmp_path / "out"
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    extracted = ExtractedPdf(
        title="Sample",
        pages=[
            ExtractedPage(page_number=1, text="Chapter One\n\nHello."),
            ExtractedPage(page_number=2, text="Chapter Two\n\nWorld."),
        ],
        toc=[(1, "Chapter One", 1), (1, "Chapter Two", 2)],
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.PdfExtractor.extract",
        lambda self, path: extracted,
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.core.merge_segments",
        lambda segments, output_path, chapters_dir=None: (
            output_path.write_bytes(b"m4b"),
            output_path,
        )[1],
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.wait_until_free",
        lambda self, *args, **kwargs: None,
    )
    tts = RecordingTTS()
    mock_run, mock_seg = _make_tts_mock_and_manifest_patch(tts)
    monkeypatch.setattr("audiobook_ai.gpu.orchestrate.run_tts_phase", mock_run)
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.require_safe_headroom",
        lambda self, *args, **kwargs: type("Snap", (), {"free_mib": 9999})(),
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.orchestrate._segments_from_manifest",
        mock_seg,
    )

    llm = RecordingLLM(dialogues_per_chapter=1, use_remote=True)
    run_generate(
        pdf,
        work_dir=work,
        llm=llm,
        tts=tts,
        voice_generator=StubVoiceGenerator(),
        skip_preflight=True,
        tts_async_overlap=0,
    )
    # unload before VD (ch-001) + unload before TTS; no third unload between chapters.
    assert llm.events.count("unload") == 2
    assert llm.events == [
        "interpret:ch-001",
        "interpret:ch-002",
        "unload",
        "unload",
    ]


def test_batched_voice_design_single_unload_for_all_characters(
    tmp_path: Path, monkeypatch
) -> None:
    """Voice design is batched after all chapters; only 2 unloads total
    (one for batch voice-design, one for TTS)."""
    work = tmp_path / "out"
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    extracted = ExtractedPdf(
        title="Sample",
        pages=[
            ExtractedPage(page_number=1, text="Chap One\nHello."),
            ExtractedPage(page_number=2, text="Chap Two\nWorld."),
            ExtractedPage(page_number=3, text="Chap Three\nFoo."),
        ],
        toc=[(1, "Chap One", 1), (1, "Chap Two", 2), (1, "Chap Three", 3)],
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.PdfExtractor.extract",
        lambda self, path: extracted,
    )
    monkeypatch.setattr(
        "audiobook_ai.pipeline.core.merge_segments",
        lambda segments, output_path, chapters_dir=None: (
            output_path.write_bytes(b"m4b"),
            output_path,
        )[1],
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.wait_until_free",
        lambda self, *args, **kwargs: None,
    )
    tts = RecordingTTS()
    mock_run, mock_seg = _make_tts_mock_and_manifest_patch(tts)
    monkeypatch.setattr("audiobook_ai.gpu.orchestrate.run_tts_phase", mock_run)
    monkeypatch.setattr(
        "audiobook_ai.gpu.guardian.VRAMGuardian.require_safe_headroom",
        lambda self, *args, **kwargs: type("Snap", (), {"free_mib": 9999})(),
    )
    monkeypatch.setattr(
        "audiobook_ai.gpu.orchestrate._segments_from_manifest",
        mock_seg,
    )

    llm = RecordingLLM(dialogues_per_chapter=1, use_remote=True)
    run_generate(
        pdf,
        work_dir=work,
        llm=llm,
        tts=tts,
        voice_generator=StubVoiceGenerator(),
        skip_preflight=True,
        tts_async_overlap=0,
    )
    # No interleaved unloads — all interpretations first, then batched.
    assert llm.events == [
        "interpret:ch-001",
        "interpret:ch-002",
        "interpret:ch-003",
        "unload",  # before batched voice-design
        "unload",  # before TTS
    ]


def test_parler_load_target_mib_config() -> None:
    """Verify PARLER_BEFORE_LOAD_TARGET_MIB is 4096 (calibrated for 24 GB GPUs)."""
    from audiobook_ai import config

    assert config.PARLER_BEFORE_LOAD_TARGET_MIB == 4096


def test_parler_model_uses_float16() -> None:
    """Verify ParlerVoiceGenerator._ensure_model uses conditional dtype:
    float32 on CPU, float16 on GPU."""
    import inspect
    from audiobook_ai.voice.generator import ParlerVoiceGenerator

    source = inspect.getsource(ParlerVoiceGenerator._ensure_model)
    assert "torch_dtype" in source
    assert "torch.float16" in source
    assert "torch.float32" in source
    assert 'device == "cpu"' in source
