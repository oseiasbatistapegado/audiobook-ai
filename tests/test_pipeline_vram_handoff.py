"""Pipeline VRAM handoff orchestration tests (mocked extract/TTS/LLM/merge)."""

from __future__ import annotations

from pathlib import Path

from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.models.audio import AudioSegment
from audiobook_ai.models.book import Chapter, ExtractedPage, ExtractedPdf
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.llm import LLMChapterResponse, StoryUpdates
from audiobook_ai.models.story import StoryState
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.pipeline import run_generate
from audiobook_ai.tts.base import TTSBackend


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
            data=b"RIFF",
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
        "audiobook_ai.pipeline.merge_segments",
        lambda segments, output_path, chapters_dir=None: (
            output_path.write_bytes(b"m4b"),
            output_path,
        )[1],
    )

    tts = RecordingTTS()
    llm = RecordingLLM(dialogues_per_chapter=2, use_remote=True)
    progress: list[tuple[str, str]] = []

    result = run_generate(
        pdf,
        work_dir=work,
        llm=llm,
        tts=tts,
        skip_preflight=True,
        progress_callback=lambda stage, detail: progress.append((stage, detail)),
    )
    assert result.exists()

    # Two chapters × (interpret → unload → synthesize×2). Orchestrator no longer
    # holds a resident Fish engine, so injected TTS has no release()/load cycle.
    assert llm.events == [
        "interpret:ch-001",
        "unload",
        "interpret:ch-002",
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

    stages = [s for s, _ in progress]
    assert "voice-design" in stages or "tts" in stages


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
        "audiobook_ai.pipeline.merge_segments",
        lambda segments, output_path, chapters_dir=None: (
            output_path.write_bytes(b"m4b"),
            output_path,
        )[1],
    )

    tts = RecordingTTS()
    llm = RecordingLLM(dialogues_per_chapter=1, use_remote=False)
    run_generate(pdf, work_dir=work, llm=llm, tts=tts, skip_preflight=True)
    assert llm.events == ["interpret:ch-001"]
    assert "unload" not in llm.events
