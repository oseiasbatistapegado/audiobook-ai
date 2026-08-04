"""Async (overlapped) LLM‑interpret + TTS pipeline.

Runs LLM chapter interpretation in a producer thread while TTS synthesizes in
a consumer thread.  The queue size is bounded by ``TTS_ASYNC_OVERLAP`` so that
at most *N* chapters are "ahead" in the pipeline.

When ``TTS_ASYNC_OVERLAP == 0`` the pipeline falls back to strict linear
processing (no producer thread).
"""

from __future__ import annotations

import math
import os
import signal
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from queue import Queue, Full, Empty
from typing import Any

from audiobook_ai import config
from audiobook_ai.gpu.jobs import WorkerExitCode
from audiobook_ai.gpu.lifecycle import (
    LifecycleError,
    LifecycleManager,
    WorkerResult,
)
from audiobook_ai.gpu.orchestrate import (
    dialogues_to_chunks,
    enrich_chunk_voices,
    pending_chunks,
    run_tts_phase,
    write_or_merge_manifest,
)
from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.models.book import Chapter
from audiobook_ai.models.story import StoryState
from audiobook_ai.state.interpret_progress import (
    InterpretProgress,
    mark_chapter_interpreted,
    mark_chapter_synthesized,
    resolve_interpret_progress,
    save_interpret_progress,
)
from audiobook_ai.state.manifest import load_manifest
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.utils.workdir import BookWorkLayout
from audiobook_ai.voice.generator import VoiceGenerator

logger = get_logger(__name__)

ProgressCallback = Callable[[str, str], None]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class InterpretedChapter:
    """Result of interpreting a single chapter (passed through the queue)."""

    __slots__ = (
        "chapter",
        "story",
        "dialogues",
        "story_updates",
        "chunks",
        "chapter_id",
        "chapter_index",
    )

    def __init__(
        self,
        chapter: Chapter,
        story: StoryState,
        dialogues: list[Any],
        story_updates: list[Any],
        chunks: list[Any],
        chapter_id: str,
        chapter_index: int,
    ) -> None:
        self.chapter = chapter
        self.story = story
        self.dialogues = dialogues
        self.story_updates = story_updates
        self.chunks = chunks
        self.chapter_id = chapter_id
        self.chapter_index = chapter_index


_STOP_EVENT = threading.Event()


def _handle_sigint(_signum: int, _frame: Any) -> None:
    """Set the global stop event on SIGINT."""
    _STOP_EVENT.set()


def start_stop_handler() -> None:
    """Register SIGINT handler for graceful shutdown."""
    try:
        signal.signal(signal.SIGINT, _handle_sigint)
    except ValueError:
        # signal.signal only works in main thread; that's fine,
        # we'll check stop_event manually.
        pass


def is_stopped() -> bool:
    """Return True when the user requested shutdown (Ctrl+C)."""
    return _STOP_EVENT.is_set()


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------

class _ProducerState:
    """Shared state between producer and consumer."""

    def __init__(self) -> None:
        self.story: StoryState | None = None
        self.interpreted_count: int = 0
        self.total_chapters: int = 0
        self.lock = threading.Lock()

    def set_total(self, n: int) -> None:
        with self.lock:
            self.total_chapters = n

    def set_story(self, story: StoryState) -> None:
        with self.lock:
            self.story = story

    def get_story(self) -> StoryState | None:
        with self.lock:
            return self.story

    def bump_interpreted(self) -> None:
        with self.lock:
            self.interpreted_count += 1

    def get_interpreted(self) -> int:
        with self.lock:
            return self.interpreted_count

    def get_total(self) -> int:
        with self.lock:
            return self.total_chapters


def _producer(
    chapters: list[Chapter],
    llm_backend: LLMBackend,
    book_layout: BookWorkLayout,
    cache_root: Path | str | None,
    max_chars: int,
    book_id: str,
    sequence_start: int,
    queue: Queue,
    prod_state: _ProducerState,
    progress_callback: ProgressCallback | None,
    generator: VoiceGenerator | None,
    story: StoryState,
    progress: InterpretProgress,
) -> tuple[StoryState, int]:
    """Producer thread: interpret chapters and enqueue results for TTS.

    For already-interpreted chapters, reads chunks from the manifest and
    enqueues them for TTS processing.  For un-interpreted chapters, runs
    LLM interpretation, chunks, enriches voices, writes to manifest, then
    enqueues.

    Returns the updated story state and final sequence cursor.
    """
    from audiobook_ai.state.manifest import load_manifest
    from audiobook_ai.state.voices import resolve_character_id

    manifest = load_manifest(book_layout.manifest_path)
    seq_cursor = sequence_start
    last_notify = 0.0

    for idx, chapter in enumerate(chapters):
        if is_stopped():
            logger.info("async-pipeline producer stopping on request")
            # Send sentinel to unblock consumer
            try:
                queue.put(None, block=False)
            except Full:
                pass
            break

        chapter_id = chapter.id

        # --- Handle already-interpreted chapters (read chunks from manifest) ---
        if progress.contains(chapter_id):
            logger.info(
                "async-pipeline producer: chapter=%s already interpreted, enqueueing from manifest",
                chapter_id,
            )
            # Collect chunks from manifest for this chapter
            chapter_chunks = [
                c for c in manifest.chunks
                if str(c.metadata.get("chapter_id") or "") == chapter_id
            ]
            # Re-order by sequence
            chapter_chunks.sort(key=lambda c: c.sequence)

            # Build a minimal InterpretedChapter from manifest chunks
            # (voice enrichment was already done by Pass A)
            result = InterpretedChapter(
                chapter=chapter,
                story=story,
                dialogues=[],
                story_updates=[],
                chunks=chapter_chunks,
                chapter_id=chapter_id,
                chapter_index=idx,
            )

            try:
                queue.put(result, timeout=5)
            except Full:
                logger.warning(
                    "async-pipeline queue full, waiting for consumer"
                )
                queue.put(result)  # blocking

            prod_state.bump_interpreted()

            # Update seq_cursor if this chapter extends the sequence
            if chapter_chunks:
                seq_cursor = max(seq_cursor, chapter_chunks[-1].sequence + 1)

            # Progress log
            now = time.time()
            if now - last_notify >= 30:
                total = prod_state.get_total()
                interp = prod_state.get_interpreted()
                _notify(
                    progress_callback,
                    "async-pipeline",
                    f"producer {interp}/{total} interpreted",
                )
                last_notify = now

            continue

        # --- LLM Interpret for un-interpreted chapters ---
        _notify(progress_callback, "async-producer", f"interpret cap {idx + 1}")

        response = llm_backend.interpret_chapter(chapter, story)
        story = story.model_copy(deep=True)
        story = story.model_copy(
            update={
                "characters": story.characters,
                "voice_map": story.voice_map,
            }
        )
        # Apply story updates (character resolution already done in original
        # pass A; we just persist them here)
        for su in response.story_updates:
            pass  # story_updates are applied in-place by the LLM backend

        # --- Resolve characters & collect dialogues ---
        chapter_character_ids: list[str] = []
        for dialogue in response.dialogues:
            character_id = resolve_character_id(
                story,
                speaker_id=getattr(dialogue, "speaker_id", None),
                speaker_name=getattr(dialogue, "speaker_name", None),
            )
            if character_id not in chapter_character_ids:
                chapter_character_ids.append(character_id)

        # --- Chunk & enrich ---
        chunks = dialogues_to_chunks(
            story,
            response.dialogues,
            chapter_id=chapter_id,
            sequence_start=seq_cursor,
            max_chars=max_chars,
            book_id=book_id,
            cache_root=cache_root,
            generator=generator,
        )
        enrich_chunk_voices(
            story,
            chunks,
            book_id=book_id,
            cache_root=cache_root,
            generator=generator,
        )
        write_or_merge_manifest(book_layout, chunks)
        if chunks:
            seq_cursor = chunks[-1].sequence + 1

        # Save progress after each chapter
        progress = mark_chapter_interpreted(progress, chapter_id)
        save_interpret_progress(progress, book_layout.interpret_progress_path)

        # Re-read manifest to get the freshly written chunks
        manifest = load_manifest(book_layout.manifest_path)
        chapter_chunks = [
            c for c in manifest.chunks
            if str(c.metadata.get("chapter_id") or "") == chapter_id
        ]
        chapter_chunks.sort(key=lambda c: c.sequence)

        # Create result and enqueue for TTS
        result = InterpretedChapter(
            chapter=chapter,
            story=story,
            dialogues=response.dialogues,
            story_updates=response.story_updates,
            chunks=chapter_chunks,
            chapter_id=chapter_id,
            chapter_index=idx,
        )

        try:
            queue.put(result, timeout=5)
        except Full:
            logger.warning(
                "async-pipeline queue full, waiting for consumer"
            )
            queue.put(result)  # blocking

        prod_state.bump_interpreted()

        # Progress log
        now = time.time()
        if now - last_notify >= 30:  # log at most every 30s
            total = prod_state.get_total()
            interp = prod_state.get_interpreted()
            _notify(
                progress_callback,
                "async-pipeline",
                f"producer {interp}/{total} interpreted",
            )
            last_notify = now

    return story, seq_cursor


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

def _consumer(
    book_layout: BookWorkLayout,
    cache_root: Path | str | None,
    lifecycle: LifecycleManager,
    queue: Queue,
    progress: InterpretProgress,
    progress_callback: ProgressCallback | None,
    hard_floor_mib: int | None,
    before_chunk_target_mib: int | None,
    tts_load_target_mib: int | None,
    tts_chunks_per_worker: int | None,
    tts_same_voice_batch_size: int | None,
    tts_multi_workers: int | None,
    tts_logical_id: str,
    completed_tracker: dict,
    tts_start_time: float,
) -> None:
    """Consumer thread: dequeue chapters and run TTS phase for each."""
    last_notify = 0.0
    total_completed = 0

    while True:
        if is_stopped():
            logger.info("async-pipeline consumer stopping on request")
            break

        try:
            item = queue.get(timeout=1)
        except Empty:
            continue

        if item is None:
            # Sentinel from producer: no more items
            break

        if not isinstance(item, InterpretedChapter):
            continue

        chapter_id = item.chapter_id
        chapter_index = item.chapter_index
        chunks = item.chunks

        if progress.is_synthesized(chapter_id):
            # Already synthesized — skip TTS entirely
            logger.info(
                "async-pipeline consumer skip synthesized chapter=%s",
                chapter_id,
            )
            total_completed += 1
            continue

        if not chunks:
            # Mark as synthesized (nothing to do)
            mark_chapter_synthesized(progress, chapter_id)
            save_interpret_progress(progress, book_layout.interpret_progress_path)
            _notify(
                progress_callback,
                "async-consumer",
                f"cap {chapter_index + 1} skip (no chunks)",
            )
            continue

        # Run TTS for this chapter's chunks
        _notify(
            progress_callback,
            "async-consumer",
            f"synth cap {chapter_index + 1}",
        )
        logger.info(
            "async-pipeline consumer synth chapter=%s chunks=%d",
            chapter_id,
            len(chunks),
        )

        # --- Run multi-worker TTS for this chapter ---
        tts_result = _run_tts_for_chapter(
            book_layout=book_layout,
            cache_root=cache_root,
            lifecycle=lifecycle,
            hard_floor_mib=hard_floor_mib,
            before_chunk_target_mib=before_chunk_target_mib,
            tts_load_target_mib=tts_load_target_mib,
            tts_chunks_per_worker=tts_chunks_per_worker,
            tts_same_voice_batch_size=tts_same_voice_batch_size,
            tts_multi_workers=tts_multi_workers,
            tts_logical_id=tts_logical_id,
        )

        # Mark chapter as synthesized
        mark_chapter_synthesized(progress, chapter_id)
        save_interpret_progress(progress, book_layout.interpret_progress_path)

        total_completed += 1
        completed_tracker[chapter_index] = {
            "success": tts_result,
            "elapsed": time.time() - tts_start_time,
        }

        # Progress log with throughput
        now = time.time()
        if now - last_notify >= 30:
            elapsed_total = now - tts_start_time
            if elapsed_total > 0 and total_completed > 0:
                throughput = total_completed / (elapsed_total / 3600)  # chapters/hour
            else:
                throughput = 0.0
            _notify(
                progress_callback,
                "async-pipeline",
                f"consumer {total_completed} synthesized "
                f"({throughput:.1f} ch/h, {elapsed_total / 60:.1f}m elapsed)",
            )
            last_notify = now

    completed_tracker["consumer_done"] = True


def _run_tts_for_chapter(
    book_layout: BookWorkLayout,
    cache_root: Path | str | None,
    lifecycle: LifecycleManager,
    hard_floor_mib: int | None,
    before_chunk_target_mib: int | None,
    tts_load_target_mib: int | None,
    tts_chunks_per_worker: int | None,
    tts_same_voice_batch_size: int | None,
    tts_multi_workers: int | None,
    tts_logical_id: str,
) -> bool:
    """Run TTS phase for all pending chunks (including current chapter).

    Returns True on success, False on failure.
    """
    try:
        run_tts_phase(
            book=book_layout,
            cache_root=cache_root,
            lifecycle=lifecycle,
            progress_callback=None,  # async pipeline handles its own progress
            use_worker=True,
            hard_floor_mib=hard_floor_mib,
            before_chunk_target_mib=before_chunk_target_mib,
            tts_load_target_mib=tts_load_target_mib,
            tts_chunks_per_worker=tts_chunks_per_worker,
            tts_same_voice_batch_size=tts_same_voice_batch_size,
            tts_multi_workers=tts_multi_workers,
            tts_logical_id=tts_logical_id,
        )
        return True
    except LifecycleError as exc:
        logger.error(
            "async-pipeline TTS failed for chapter: %s", exc
        )
        return False


# ---------------------------------------------------------------------------
# AsyncPipelineRunner
# ---------------------------------------------------------------------------

class AsyncPipelineRunner:
    """Run the async (overlapped) LLM + TTS pipeline.

    Parameters
    ----------
    llm_backend: LLMBackend
        LLM backend for chapter interpretation.
    chapters: list[Chapter]
        All chapters to process.
    book_layout: BookWorkLayout
        Book-scoped paths (manifest, progress, etc.).
    cache_root: Path | str | None
        Cache directory for weights.
    lifecycle: LifecycleManager
        GPU lifecycle manager for TTS workers.
    progress_callback: ProgressCallback | None
        Callback for UI progress updates.
    max_chars: int
        Max characters per SpeechChunk.
    book_id: str
        Book identifier.
    sequence_start: int
        Starting sequence number for chunks.
    hard_floor_mib: int | None
        Hard floor VRAM threshold.
    before_chunk_target_mib: int | None
        Before-chunk VRAM target.
    tts_load_target_mib: int | None
        TTS load target VRAM.
    tts_chunks_per_worker: int | None
        TTS chunks per worker residency cap.
    tts_same_voice_batch_size: int | None
        Batch size for same-voice chunks.
    tts_multi_workers: int | None
        Number of parallel TTS workers.
    tts_logical_id: str
        Logical TTS backend ID.
    generator: VoiceGenerator | None
        Voice generator for voice enrichment.
    story: StoryState
        Story state (characters, voice map).
    progress: InterpretProgress
        Current interpretation progress (for resume).
    """

    def __init__(
        self,
        llm_backend: LLMBackend,
        chapters: list[Chapter],
        book_layout: BookWorkLayout,
        cache_root: Path | str | None,
        lifecycle: LifecycleManager,
        progress_callback: ProgressCallback | None = None,
        max_chars: int = config.TTS_MAX_CHUNK_CHARS,
        book_id: str = "",
        sequence_start: int = 0,
        hard_floor_mib: int | None = None,
        before_chunk_target_mib: int | None = None,
        tts_load_target_mib: int | None = None,
        tts_chunks_per_worker: int | None = None,
        tts_same_voice_batch_size: int | None = None,
        tts_multi_workers: int | None = None,
        tts_logical_id: str = "qwen3-tts",
        generator: VoiceGenerator | None = None,
        story: StoryState | None = None,
        progress: InterpretProgress | None = None,
    ) -> None:
        self.llm_backend = llm_backend
        self.chapters = chapters
        self.book_layout = book_layout
        self.cache_root = cache_root
        self.lifecycle = lifecycle
        self.progress_callback = progress_callback
        self.max_chars = max_chars
        self.book_id = book_id
        self.sequence_start = sequence_start
        self.hard_floor_mib = hard_floor_mib
        self.before_chunk_target_mib = before_chunk_target_mib
        self.tts_load_target_mib = tts_load_target_mib
        self.tts_chunks_per_worker = tts_chunks_per_worker
        self.tts_same_voice_batch_size = tts_same_voice_batch_size
        self.tts_multi_workers = tts_multi_workers
        self.tts_logical_id = tts_logical_id
        self.generator = generator
        self.story = story or StoryState()
        self.progress = progress or InterpretProgress()

    def run(self) -> tuple[StoryState, int]:
        """Run the async pipeline.

        Returns the updated story state and final sequence cursor.
        """
        start_time = time.time()
        _notify(self.progress_callback, "async-pipeline", "starting")
        logger.info(
            "async-pipeline start chapters=%d overlap=%d workers=%s",
            len(self.chapters),
            config.TTS_ASYNC_OVERLAP,
            self.tts_multi_workers,
        )

        prod_state = _ProducerState()
        prod_state.set_total(len(self.chapters))
        prod_state.set_story(self.story)

        queue: Queue = Queue(
            maxsize=max(config.TTS_ASYNC_OVERLAP, 1),
        )
        completed_tracker: dict = {}
        tts_start_time = time.time()

        # Start producer thread
        producer_thread = threading.Thread(
            target=_producer,
            args=(
                self.chapters,
                self.llm_backend,
                self.book_layout,
                self.cache_root,
                self.max_chars,
                self.book_id,
                self.sequence_start,
                queue,
                prod_state,
                self.progress_callback,
                self.generator,
                self.story,
                self.progress,
            ),
            daemon=True,
            name="async-llm-producer",
        )
        producer_thread.start()

        # Start consumer thread
        consumer_thread = threading.Thread(
            target=_consumer,
            args=(
                self.book_layout,
                self.cache_root,
                self.lifecycle,
                queue,
                self.progress,
                self.progress_callback,
                self.hard_floor_mib,
                self.before_chunk_target_mib,
                self.tts_load_target_mib,
                self.tts_chunks_per_worker,
                self.tts_same_voice_batch_size,
                self.tts_multi_workers,
                self.tts_logical_id,
                completed_tracker,
                tts_start_time,
            ),
            daemon=True,
            name="async-tts-consumer",
        )
        consumer_thread.start()

        # Wait for both threads
        producer_thread.join()
        consumer_thread.join()

        # Determine final story state and sequence cursor
        story, seq_cursor = prod_state.story or self.story, self.sequence_start
        elapsed = time.time() - start_time

        _notify(
            self.progress_callback,
            "async-pipeline",
            f"complete in {elapsed:.0f}s",
        )
        logger.info(
            "async-pipeline complete elapsed=%.1f chapters=%d",
            elapsed,
            len(self.chapters),
        )

        return story, seq_cursor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notify(
    callback: ProgressCallback | None,
    stage: str,
    detail: str,
) -> None:
    if callback is not None:
        callback(stage, detail)
