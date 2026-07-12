"""End-to-end generate pipeline: Extract → Parse → Interpret → workers → Merge.

The CLI/orchestrator process does NOT load Parler or Fish Speech on the GPU.
Voice Design and Fish Speech run in isolated workers; SpeechChunks persist to
a book-scoped manifest for resume.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.audio.merge import merge_segments
from audiobook_ai.extractors.pdf import PdfExtractor
from audiobook_ai.gpu.lifecycle import LifecycleManager
from audiobook_ai.gpu.orchestrate import (
    build_guardian,
    dialogues_to_chunks,
    enrich_chunk_voices,
    run_fish_phase,
    run_voice_design_phase,
    write_or_merge_manifest,
)
from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.llm.ollama_backend import OllamaBackend
from audiobook_ai.parser.chapters import parse_chapters
from audiobook_ai.preflight import run_preflight
from audiobook_ai.state.store import load_story_state, save_story_state
from audiobook_ai.state.voices import apply_story_updates, resolve_character_id
from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.tts.factory import get_tts_backend
from audiobook_ai.tts.fish_speech import FishSpeechBackend
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.utils.workdir import WorkDirLayout, ensure_work_dir
from audiobook_ai.voice.book_id import compute_book_id
from audiobook_ai.voice.generator import VoiceGenerator, get_voice_generator
from audiobook_ai.weights.manager import ModelManager
from audiobook_ai.weights.fish import resolve_fish_model

logger = get_logger(__name__)

ProgressCallback = Callable[[str, str], None]


def run_generate(
    pdf_path: Path,
    *,
    model: str = config.DEFAULT_OLLAMA_MODEL,
    fish_model: str = config.DEFAULT_FISH_MODEL,
    output: Path | None = None,
    work_dir: Path | str | None = None,
    ollama_host: str = config.DEFAULT_OLLAMA_HOST,
    cache_dir: Path | str | None = None,
    llm: LLMBackend | None = None,
    tts: TTSBackend | None = None,
    voice_generator: VoiceGenerator | None = None,
    progress_callback: ProgressCallback | None = None,
    skip_preflight: bool = False,
    hard_floor_mib: int | None = None,
    before_chunk_target_mib: int | None = None,
    fish_load_target_mib: int | None = None,
    parler_load_target_mib: int | None = None,
    tts_max_chunk_chars: int | None = None,
    fish_chunks_per_worker: int | None = None,
    use_gpu_workers: bool | None = None,
) -> Path:
    """Run the full MVP pipeline and return the final audiobook path."""
    fish_def = resolve_fish_model(fish_model)
    # Presets for the selected Fish alias when the user did not override knobs.
    if tts_max_chunk_chars is None:
        tts_max_chunk_chars = fish_def.tts_max_chunk_chars
    if fish_load_target_mib is None:
        fish_load_target_mib = fish_def.before_load_target_mib

    layout = ensure_work_dir(work_dir)
    output_path = _resolve_output(output, layout)

    # Injected TTS (unit tests) → in-process synthesis path, no real workers.
    workers_enabled = use_gpu_workers if use_gpu_workers is not None else tts is None

    if not skip_preflight:
        check_tts = workers_enabled or isinstance(tts, FishSpeechBackend)
        _notify(progress_callback, "preflight", "checking dependencies")
        run_preflight(
            ollama_host=ollama_host,
            model=model,
            check_tts_imports=check_tts,
        )

    started = time.perf_counter()
    logger.info(
        "pipeline start stage=extract pdf=%s work_dir=%s output=%s fish_model=%s",
        pdf_path,
        layout.root,
        output_path,
        fish_def.alias,
    )

    extractor = PdfExtractor()
    extracted = extractor.extract(Path(pdf_path))
    _notify(progress_callback, "extract", extracted.title)

    book_id = compute_book_id(Path(pdf_path))
    book_layout = layout.book_layout(book_id)
    logger.info("pipeline book_id=%s book_root=%s", book_id, book_layout.root)

    book = parse_chapters(extracted)
    _notify(progress_callback, "parse", f"{len(book.chapters)} chapters")

    llm_backend = llm or OllamaBackend(
        model=model,
        host=ollama_host,
        cache_dir=layout.cache_dir,
    )

    # Weights-only ensure in orchestrator when using real Fish workers.
    if workers_enabled:
        manager = ModelManager(cache_dir=cache_dir)
        tts_probe = get_tts_backend(
            config.DEFAULT_TTS_BACKEND,
            cache_dir=cache_dir,
            manager=manager,
            fish_model=fish_def.alias,
        )
        if isinstance(tts_probe, FishSpeechBackend):
            _notify(progress_callback, "model-ensure", fish_def.alias)

            def _model_progress(message: str, fraction: float | None) -> None:
                detail = message if fraction is None else f"{message} {fraction:.0%}"
                if message == "cache-hit":
                    _notify(progress_callback, "model-ensure", "cache hit")
                elif message.startswith("download"):
                    _notify(progress_callback, "model-download", detail)
                else:
                    _notify(progress_callback, "model-ensure", detail)

            tts_probe.ensure_weights(progress_callback=_model_progress)
            _notify(progress_callback, "model-ensure", "weights ready")
            # Do NOT keep engine loaded in orchestrator.
            tts_probe.release()

    story_path = book_layout.story_path
    # Migrate: prefer book-scoped story; fall back to legacy root story once.
    if not story_path.is_file() and layout.story_path.is_file():
        story = load_story_state(layout.story_path)
        save_story_state(story, story_path)
    else:
        story = load_story_state(story_path)

    generator = voice_generator or get_voice_generator()
    guardian = build_guardian(
        hard_floor_mib=hard_floor_mib,
        before_chunk_target_mib=before_chunk_target_mib,
        fish_load_target_mib=fish_load_target_mib,
        parler_load_target_mib=parler_load_target_mib,
    )
    lifecycle = LifecycleManager(guardian)
    max_chars = tts_max_chunk_chars or config.TTS_MAX_CHUNK_CHARS
    sequence_cursor = 0

    for chapter in book.chapters:
        chapter_started = time.perf_counter()
        _vram_handoff(
            progress_callback,
            "release-tts",
            "pipeline stage=vram-handoff action=release-tts chapter=%s",
            chapter.id,
        )
        # No resident Fish worker expected between chapters; lease must be free.
        if lifecycle.active_backend is not None:
            raise RuntimeError(
                f"GPU lease still held by {lifecycle.active_backend} before interpret"
            )

        logger.info(
            "pipeline stage=interpret chapter=%s title=%s backend=ollama model=%s",
            chapter.id,
            chapter.title,
            model,
        )
        _notify(progress_callback, "interpret", chapter.id)

        response = llm_backend.interpret_chapter(chapter, story)
        apply_story_updates(story, response.story_updates)

        chapter_character_ids: list[str] = []
        for dialogue in response.dialogues:
            character_id = resolve_character_id(
                story,
                speaker_id=dialogue.speaker_id,
                speaker_name=dialogue.speaker_name,
            )
            if character_id not in chapter_character_ids:
                chapter_character_ids.append(character_id)

        used_remote = bool(getattr(llm_backend, "last_used_remote", False))
        if used_remote:
            _vram_handoff(
                progress_callback,
                "unload-llm",
                "pipeline stage=vram-handoff action=unload-llm chapter=%s",
                chapter.id,
            )
            llm_backend.unload()
            # Ollama keep_alive=0 reclaim is asynchronous on ROCm; wait before
            # subsequent GPU load gates (Voice Design and/or Fish).
            lifecycle.guardian.wait_until_free(
                float(fish_load_target_mib or config.FISH_BEFORE_LOAD_TARGET_MIB),
                backend="ollama",
                event="wait_llm_unload",
            )

        if chapter_character_ids:
            _notify(
                progress_callback,
                "voice-design",
                f"{len(chapter_character_ids)} characters",
            )
            run_voice_design_phase(
                story,
                chapter_character_ids,
                book=book_layout,
                cache_root=cache_dir,
                lifecycle=lifecycle,
                progress_callback=progress_callback,
                use_worker=workers_enabled,
                generator=generator,
                fish_load_target_mib=fish_load_target_mib,
            )
            save_story_state(story, story_path)

        if response.dialogues:
            chunks = dialogues_to_chunks(
                story,
                response.dialogues,
                chapter_id=chapter.id,
                sequence_start=sequence_cursor,
                max_chars=max_chars,
                book_id=book_id,
                cache_root=cache_dir,
                generator=generator,
            )
            enrich_chunk_voices(
                story,
                chunks,
                book_id=book_id,
                cache_root=cache_dir,
                generator=generator,
            )
            write_or_merge_manifest(book_layout, chunks)
            if chunks:
                sequence_cursor = chunks[-1].sequence + 1

            skipped = 0
            if book_layout.manifest_path.is_file():
                from audiobook_ai.state.manifest import load_manifest, pending_chunks

                man = load_manifest(book_layout.manifest_path)
                pending = {e.id for e in pending_chunks(man, book_root=book_layout.root)}
                skipped = sum(1 for c in chunks if c.id not in pending)
                if skipped:
                    _notify(
                        progress_callback,
                        "tts-resume",
                        f"skip {skipped} completed chunks",
                    )

            _vram_handoff(
                progress_callback,
                "load-tts",
                "pipeline stage=vram-handoff action=spawn-fish chapter=%s",
                chapter.id,
            )
            run_fish_phase(
                book=book_layout,
                cache_root=cache_dir,
                lifecycle=lifecycle,
                progress_callback=progress_callback,
                use_worker=workers_enabled,
                tts=tts,
                hard_floor_mib=hard_floor_mib,
                before_chunk_target_mib=before_chunk_target_mib,
                fish_load_target_mib=fish_load_target_mib,
                fish_chunks_per_worker=fish_chunks_per_worker,
                fish_model_alias=fish_def.alias,
                fish_logical_id=fish_def.logical_id,
            )

        _vram_handoff(
            progress_callback,
            "release-tts",
            "pipeline stage=vram-handoff action=release-tts chapter=%s after=tts",
            chapter.id,
        )

        save_story_state(story, story_path)
        elapsed = time.perf_counter() - chapter_started
        logger.info(
            "pipeline chapter done chapter=%s seconds=%.2f",
            chapter.id,
            elapsed,
        )

    # Merge from manifest order (not readdir).
    from audiobook_ai.gpu.orchestrate import _segments_from_manifest

    if book_layout.manifest_path.is_file():
        all_segments = _segments_from_manifest(book_layout)
    else:
        all_segments = []

    logger.info("pipeline stage=merge segments=%s", len(all_segments))
    _notify(progress_callback, "merge", str(output_path))
    result = merge_segments(
        all_segments,
        output_path,
        chapters_dir=book_layout.chapters_dir,
    )

    # Ensure Voice Design model is not left resident in orchestrator.
    unload = getattr(generator, "unload", None)
    if callable(unload):
        try:
            unload()
        except Exception:  # noqa: BLE001
            logger.debug("orchestrator voice generator unload failed", exc_info=True)

    total = time.perf_counter() - started
    logger.info("pipeline complete output=%s seconds=%.2f", result, total)
    return result


def _resolve_output(output: Path | None, layout: WorkDirLayout) -> Path:
    if output is None:
        return layout.default_output_path()
    path = Path(output)
    if path.suffix.lower() not in {".m4b", ".mp3"}:
        path = path.with_suffix(".m4b")
    return path


def _notify(
    callback: ProgressCallback | None,
    stage: str,
    detail: str,
) -> None:
    if callback is not None:
        callback(stage, detail)


def _vram_handoff(
    callback: ProgressCallback | None,
    detail: str,
    log_fmt: str,
    *log_args: object,
) -> None:
    logger.info(log_fmt, *log_args)
    _notify(callback, "vram-handoff", detail)
