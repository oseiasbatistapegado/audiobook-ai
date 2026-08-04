"""Orchestrate isolated GPU workers for Voice Design and TTS."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.gpu.guardian import GuardianConfig, VRAMGuardian
from audiobook_ai.gpu.jobs import (
    JobConfig,
    JobDefinition,
    WorkerExitCode,
    job_dir,
    write_job,
)
from audiobook_ai.gpu.lifecycle import (
    CompletedProcessLike,
    LifecycleError,
    LifecycleManager,
    SpawnFn,
    merge_pytorch_alloc_conf,
)
from audiobook_ai.gpu.memory import SystemMemoryProvider
from audiobook_ai.gpu.runtimes import (
    resolve_tts_python,
    resolve_voice_design_python,
    worker_env,
)
from audiobook_ai.models.audio import AudioSegment
from audiobook_ai.models.speech import SpeechChunk, partition_dialogues
from audiobook_ai.models.story import StoryState
from audiobook_ai.state.manifest import (
    ChunkStatus,
    create_manifest,
    load_manifest,
    mark_completed,
    pending_chunks,
    relative_audio_path,
    save_manifest,
)
from audiobook_ai.state.store import load_story_state, save_story_state
from audiobook_ai.state.voices import ensure_voice, ensure_voices_batch, resolve_character_id
from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.utils.workdir import BookWorkLayout
from audiobook_ai.voice.generator import VoiceGenerator

logger = get_logger(__name__)

ProgressCallback = Callable[[str, str], None]


def build_guardian(
    *,
    hard_floor_mib: int | None = None,
    before_chunk_target_mib: int | None = None,
    tts_load_target_mib: int | None = None,
    fish_load_target_mib: int | None = None,
    parler_load_target_mib: int | None = None,
) -> VRAMGuardian:
    load_tts = (
        tts_load_target_mib
        if tts_load_target_mib is not None
        else (
            fish_load_target_mib
            if fish_load_target_mib is not None
            else config.TTS_BEFORE_LOAD_TARGET_MIB
        )
    )
    cfg = GuardianConfig(
        hard_floor_mib=hard_floor_mib or config.HARD_FLOOR_MIB,
        before_chunk_target_mib=before_chunk_target_mib
        or config.BEFORE_CHUNK_TARGET_MIB,
        load_targets_mib={
            "tts": load_tts,
            "qwen3-tts": load_tts,
            "parler": parler_load_target_mib or config.PARLER_BEFORE_LOAD_TARGET_MIB,
        },
    )
    return VRAMGuardian(SystemMemoryProvider(), cfg=cfg)


def dialogues_to_chunks(
    story: StoryState,
    dialogues: list,
    *,
    chapter_id: str,
    sequence_start: int = 0,
    max_chars: int | None = None,
    book_id: str,
    cache_root: Path | str | None,
    generator: VoiceGenerator | None = None,
) -> list[SpeechChunk]:
    """Partition dialogues and attach resolved voice_id metadata."""
    total = len(dialogues)
    needs_review_count = sum(
        1 for d in dialogues if getattr(d, "status", None) == "needs_review"
    )
    if needs_review_count > 0 and total > 0:
        ratio = needs_review_count / total
        if ratio > 0.05:
            logger.warning(
                "needs_review units exceed 5%% of chapter "
                "chapter=%s count=%d total=%d ratio=%.1f%%",
                chapter_id,
                needs_review_count,
                total,
                ratio * 100,
            )

    def _resolve(dialogue: object) -> str:
        return resolve_character_id(
            story,
            speaker_id=getattr(dialogue, "speaker_id", None),
            speaker_name=getattr(dialogue, "speaker_name", None),
        )

    chunks = partition_dialogues(
        dialogues,
        chapter_id=chapter_id,
        max_chars=max_chars,
        resolve_character_id=_resolve,
        sequence_start=sequence_start,
    )
    for chunk in chunks:
        character_id = chunk.metadata.get("character_id")
        if not character_id:
            continue
        # Resolve voice from story map when already assigned; otherwise leave
        # for post-voice-design enrichment.
        voice_id = story.voice_map.get(str(character_id))
        if voice_id:
            chunk.metadata["voice_id"] = voice_id
        else:
            # ensure_voice may be used in injected/test path; worker path
            # assigns during voice-design phase.
            pass
    return chunks


def enrich_chunk_voices(
    story: StoryState,
    chunks: list[SpeechChunk],
    *,
    book_id: str,
    cache_root: Path | str | None = None,
    generator: VoiceGenerator | None = None,
) -> None:
    for chunk in chunks:
        character_id = chunk.metadata.get("character_id")
        if not character_id:
            chunk.metadata.setdefault("voice_id", config.NARRATOR_VOICE_ID)
            continue
        voice_id = ensure_voice(
            story,
            str(character_id),
            book_id=book_id,
            cache_root=cache_root,
            generator=generator,
        )
        chunk.metadata["voice_id"] = voice_id


def write_or_merge_manifest(
    book: BookWorkLayout,
    chunks: list[SpeechChunk],
) -> None:
    """Create or append pending chunks into the book manifest."""
    if book.manifest_path.is_file():
        manifest = load_manifest(book.manifest_path)
        existing_ids = {e.id for e in manifest.chunks}
        for chunk in chunks:
            if chunk.id in existing_ids:
                continue
            from audiobook_ai.state.manifest import ManifestChunkEntry

            manifest.chunks.append(
                ManifestChunkEntry(
                    id=chunk.id,
                    sequence=chunk.sequence,
                    text=chunk.text,
                    metadata=dict(chunk.metadata),
                    status=ChunkStatus.PENDING,
                )
            )
    else:
        manifest = create_manifest(book.book_id, chunks)
    save_manifest(manifest, book.manifest_path)


def run_voice_design_phase(
    story: StoryState,
    character_ids: list[str],
    *,
    book: BookWorkLayout,
    cache_root: Path | str | None,
    lifecycle: LifecycleManager,
    progress_callback: ProgressCallback | None = None,
    use_worker: bool = True,
    spawn_fn: SpawnFn | None = None,
    generator: VoiceGenerator | None = None,
    fish_load_target_mib: int | None = None,
) -> None:
    """Generate missing voices via isolated worker (or in-process for tests)."""
    missing = [cid for cid in character_ids if cid not in story.voice_map]
    if not missing:
        return

    if not use_worker:
        ensure_voices_batch(
            story,
            missing,
            book_id=book.book_id,
            cache_root=cache_root,
            generator=generator,
        )
        save_story_state(story, book.story_path)
        return

    job_id = f"voice-design-{uuid.uuid4().hex[:10]}"
    directory = job_dir(book.jobs_dir, job_id)
    directory.mkdir(parents=True, exist_ok=True)
    save_story_state(story, book.story_path)
    job = JobDefinition(
        job_id=job_id,
        backend="parler",
        book_id=book.book_id,
        book_root=str(book.root),
        manifest_path=str(book.manifest_path),
        character_ids=missing,
        config=JobConfig(
            before_load_target_mib=config.PARLER_BEFORE_LOAD_TARGET_MIB,
            cache_dir=str(cache_root) if cache_root else None,
        ),
    )
    write_job(directory, job)

    command = [
        resolve_voice_design_python(),
        "-m",
        "audiobook_ai.workers.voice_design",
        str(directory),
    ]
    if spawn_fn is not None:
        lifecycle._spawn_fn = spawn_fn

    lifecycle.run_worker(
        "parler",
        command,
        progress_callback=progress_callback,
        next_backend_for_release="tts",
        release_target_mib=float(
            fish_load_target_mib
            if fish_load_target_mib is not None
            else config.TTS_BEFORE_LOAD_TARGET_MIB
        ),
        env=worker_env(),
    )
    # Reload story mutations from worker.
    if book.story_path.is_file():
        updated = load_story_state(book.story_path)
        story.characters = updated.characters
        story.voice_map = updated.voice_map


def run_tts_phase(
    *,
    book: BookWorkLayout,
    cache_root: Path | str | None,
    lifecycle: LifecycleManager,
    progress_callback: ProgressCallback | None = None,
    use_worker: bool = True,
    spawn_fn: SpawnFn | None = None,
    tts: TTSBackend | None = None,
    hard_floor_mib: int | None = None,
    before_chunk_target_mib: int | None = None,
    tts_load_target_mib: int | None = None,
    fish_load_target_mib: int | None = None,
    tts_chunks_per_worker: int | None = None,
    fish_chunks_per_worker: int | None = None,
    tts_logical_id: str | None = None,
    fish_model_alias: str | None = None,
    fish_logical_id: str | None = None,
    tts_multi_workers: int | None = None,
    tts_same_voice_batch_size: int | None = None,
    tts_async_overlap: int | None = None,
) -> list[AudioSegment]:
    """Synthesize pending SpeechChunks via TTS worker (or injected TTS)."""
    del fish_model_alias, fish_logical_id  # no Fish routing
    multi_workers = (
        tts_multi_workers if tts_multi_workers is not None else config.TTS_MULTI_WORKER_COUNT
    )
    same_voice_batch = (
        tts_same_voice_batch_size
        if tts_same_voice_batch_size is not None
        else config.TTS_SAME_VOICE_BATCH_SIZE
    )
    if not book.manifest_path.is_file():
        return []

    manifest = load_manifest(book.manifest_path)
    pending = pending_chunks(manifest, book_root=book.root)
    if not pending:
        _notify(progress_callback, "tts-resume", "all chunks completed")
        return _segments_from_manifest(book)

    if not use_worker:
        assert tts is not None
        return _synthesize_injected(tts, book, pending, progress_callback)

    # ------------------------------------------------------------------
    # Multi-worker path: spawn N independent TTS workers in parallel
    # ------------------------------------------------------------------
    if multi_workers > 1:
        per_worker_mib = (
            config.TTS_PER_WORKER_VRAM_MIB + config.TTS_PER_WORKER_OVERHEAD_MIB
        )
        required_mib = multi_workers * per_worker_mib

        try:
            lifecycle.guardian.require_safe_headroom(kind="load", backend="tts")
        except Exception:  # noqa: BLE001
            logger.warning(
                "[gpu] multi-worker fallback: insufficient VRAM "
                "(needed %d MiB, have less); falling back to single-worker",
                required_mib,
            )
            multi_workers = 1

    if multi_workers > 1:
        worker_chunk_map = resolve_tts_workers(book, multi_workers)
        active_workers: list[int] = []
        for wid, chunk_ids in sorted(worker_chunk_map.items()):
            if not chunk_ids:
                continue
            active_workers.append(wid)

        if active_workers:
            _notify(progress_callback, "gpu-multi-worker", f"spawning {len(active_workers)} workers")
            logger.info(
                "[gpu] multi-worker tts workers=%d chunks=%d",
                len(active_workers),
                len(pending),
            )

            # Build per-worker command specs
            worker_specs: dict[int, Sequence[str]] = {}
            worker_dirs: dict[int, Path] = {}
            for wid in active_workers:
                chunk_ids = worker_chunk_map[wid]
                if not chunk_ids:
                    continue
                job_id = f"tts-mw-{wid}-{uuid.uuid4().hex[:8]}"
                directory = job_dir(book.jobs_dir, job_id)
                directory.mkdir(parents=True, exist_ok=True)
                worker_dirs[wid] = directory

                # Re-use same manifest + config; worker will process only its
                # assigned chunk subset via pending_chunk_ids.
                job = JobDefinition(
                    job_id=job_id,
                    backend="tts",
                    book_id=book.book_id,
                    book_root=str(book.root),
                    manifest_path=str(book.manifest_path),
                    pending_chunk_ids=chunk_ids,
                    worker_id=wid,
                    config=JobConfig(
                        hard_floor_mib=hard_floor_mib or config.HARD_FLOOR_MIB,
                        before_chunk_target_mib=before_chunk_target_mib
                        or config.BEFORE_CHUNK_TARGET_MIB,
                        before_load_target_mib=load_target,
                        tts_chunks_per_worker=residency_cap or 0,
                        fish_chunks_per_worker=residency_cap or 0,
                        tts_same_voice_batch_size=same_voice_batch,
                        cache_dir=str(cache_root) if cache_root else None,
                        tts_logical_id=tts_logical_id or "qwen3-tts",
                    ),
                )
                write_job(directory, job)
                worker_specs[wid] = [
                    resolve_tts_python(),
                    "-m",
                    "audiobook_ai.workers.qwen3_tts",
                    str(directory),
                ]

            # Spawn all workers
            lifecycle.spawn_multi_workers(
                worker_specs,
                env=merge_pytorch_alloc_conf(),
            )

            # Join all workers — each processes its own chunk subset
            results = lifecycle.join_multi_workers(
                list(worker_specs.keys()),
            )

            # Check for fatal failures
            fatal_workers: list[int] = []
            for wid, result in results.items():
                if result.exit_code == int(WorkerExitCode.FATAL):
                    fatal_workers.append(wid)
                    logger.error(
                        "[gpu] multi-worker fatal w%d exit=%d stderr=%s",
                        wid,
                        result.exit_code,
                        result.stderr[:500] if result.stderr else "",
                    )

                # Log per-worker progress
                completed_in_worker = result.stdout.count("completed")
                if completed_in_worker:
                    logger.info(
                        "[gpu] event=multi_worker_done worker=%d completed_chunks=%d",
                        wid,
                        completed_in_worker,
                    )

            if fatal_workers:
                raise LifecycleError(
                    f"TTS multi-worker fatal exit on worker(s) {fatal_workers}; "
                    f"check logs for details"
                )

            _notify(
                progress_callback,
                "gpu-multi-worker",
                f"all {len(results)} workers complete",
            )
            logger.info("[gpu] multi-worker tts phase complete workers=%d", len(results))

            # Verify all chunks completed in manifest
            final_manifest = load_manifest(book.manifest_path)
            still_pending = pending_chunks(final_manifest, book_root=book.root)
            if still_pending:
                raise LifecycleError(
                    f"TTS multi-worker ended with {len(still_pending)} pending chunks"
                )

            return _segments_from_manifest(book)

    # --- Single-worker path (original) ---
    chunk_attempts: dict[str, int] = {
        e.id: e.attempts for e in manifest.chunks
    }
    max_attempts = config.SPEECH_CHUNK_MAX_ATTEMPTS
    last_job_dir: list[Path] = []
    residency_cap = (
        config.TTS_CHUNKS_PER_WORKER
        if tts_chunks_per_worker is None and fish_chunks_per_worker is None
        else (
            tts_chunks_per_worker
            if tts_chunks_per_worker is not None
            else fish_chunks_per_worker
        )
    )
    load_target = (
        tts_load_target_mib
        if tts_load_target_mib is not None
        else (
            fish_load_target_mib
            if fish_load_target_mib is not None
            else config.TTS_BEFORE_LOAD_TARGET_MIB
        )
    )

    def has_pending() -> bool:
        current = load_manifest(book.manifest_path)
        return bool(pending_chunks(current, book_root=book.root))

    def completed_count() -> int:
        current = load_manifest(book.manifest_path)
        return sum(1 for e in current.chunks if e.status == ChunkStatus.COMPLETED)

    def _last_result():
        if not last_job_dir:
            return None
        from audiobook_ai.gpu.jobs import read_result

        try:
            return read_result(last_job_dir[-1])
        except Exception:  # noqa: BLE001
            return None

    def _last_restart_reason() -> str | None:
        prev = _last_result()
        return prev.restart_reason if prev is not None else None

    def _last_oom_chunk_id() -> str | None:
        prev = _last_result()
        return prev.oom_chunk_id if prev is not None else None

    def command_factory() -> Sequence[str]:
        if last_job_dir:
            from audiobook_ai.gpu.jobs import WorkerExitCode, read_result

            try:
                prev = read_result(last_job_dir[-1])
            except Exception:  # noqa: BLE001
                prev = None
            if (
                prev is not None
                and prev.failed_chunk_id
                and prev.exit_code == int(WorkerExitCode.FATAL)
            ):
                cid = prev.failed_chunk_id
                chunk_attempts[cid] = chunk_attempts.get(cid, 0) + 1

        job_id = f"tts-{uuid.uuid4().hex[:10]}"
        directory = job_dir(book.jobs_dir, job_id)
        directory.mkdir(parents=True, exist_ok=True)
        last_job_dir.append(directory)
        current = load_manifest(book.manifest_path)
        pending_now = pending_chunks(current, book_root=book.root)
        for entry in pending_now:
            if chunk_attempts.get(entry.id, 0) >= max_attempts:
                raise LifecycleError(
                    f"SpeechChunk {entry.id} failed {max_attempts} times; aborting"
                )
        job = JobDefinition(
            job_id=job_id,
            backend="tts",
            book_id=book.book_id,
            book_root=str(book.root),
            manifest_path=str(book.manifest_path),
            pending_chunk_ids=[e.id for e in pending_now],
            worker_id=None,  # single-worker path; multi-worker sets per-job
            config=JobConfig(
                hard_floor_mib=hard_floor_mib or config.HARD_FLOOR_MIB,
                before_chunk_target_mib=before_chunk_target_mib
                or config.BEFORE_CHUNK_TARGET_MIB,
                before_load_target_mib=load_target,
                tts_chunks_per_worker=residency_cap or 0,
                fish_chunks_per_worker=residency_cap or 0,
                tts_same_voice_batch_size=same_voice_batch,
                cache_dir=str(cache_root) if cache_root else None,
                tts_logical_id=tts_logical_id or "qwen3-tts",
            ),
        )
        write_job(directory, job)
        return [
            resolve_tts_python(),
            "-m",
            "audiobook_ai.workers.qwen3_tts",
            str(directory),
        ]

    if spawn_fn is not None:
        lifecycle._spawn_fn = spawn_fn

    def counts_against_budget(_result: object) -> bool:
        """Planned guardian/residency reclaim must not charge OOM/stall gates."""
        from audiobook_ai.gpu.jobs import PLANNED_RESTART_REASONS

        reason = _last_restart_reason()
        if reason in PLANNED_RESTART_REASONS:
            return False
        return True

    def restart_reason_fn(_result: object) -> str | None:
        return _last_restart_reason()

    def oom_chunk_id_fn(_result: object) -> str | None:
        return _last_oom_chunk_id()

    result = lifecycle.run_tts_with_restarts(
        command_factory,
        has_pending=has_pending,
        progress_callback=progress_callback,
        restart_budget=config.TTS_WORKER_RESTART_BUDGET,
        counts_against_budget=counts_against_budget,
        restart_reason_fn=restart_reason_fn,
        completed_count=completed_count,
        oom_chunk_id_fn=oom_chunk_id_fn,
    )
    if not result.success and not result.controlled_restart_needed:
        if result.returncode == int(WorkerExitCode.FATAL):
            raise LifecycleError(
                f"TTS worker fatal exit: {result.stderr[-500:] or result.stdout[-500:]}"
            )

    final = load_manifest(book.manifest_path)
    still = pending_chunks(final, book_root=book.root)
    if still:
        raise LifecycleError(
            f"TTS phase ended with {len(still)} pending chunks"
        )
    return _segments_from_manifest(book)


# Back-compat alias until call sites / tests fully migrate.
run_fish_phase = run_tts_phase


def _synthesize_injected(
    tts: TTSBackend,
    book: BookWorkLayout,
    pending: list,
    progress_callback: ProgressCallback | None,
) -> list[AudioSegment]:
    from audiobook_ai.models.emotion import Emotion
    from audiobook_ai.models.tts import TTSRequest

    manifest = load_manifest(book.manifest_path)
    for entry in pending:
        _notify(progress_callback, "tts", entry.id)
        emotion_raw = entry.metadata.get("emotion", "neutral")
        try:
            emotion = Emotion(emotion_raw)
        except ValueError:
            emotion = Emotion.NEUTRAL
        request = TTSRequest(
            text=entry.text,
            voice_id=str(entry.metadata.get("voice_id") or config.NARRATOR_VOICE_ID),
            emotion=emotion,
            chapter_id=str(entry.metadata.get("chapter_id") or "chapter"),
            segment_index=entry.sequence,
        )
        segment = tts.synthesize(request)
        rel = relative_audio_path(entry.sequence)
        audio_path = book.root / rel
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        if segment.path is not None and segment.path.is_file():
            audio_path.write_bytes(segment.path.read_bytes())
        elif segment.data:
            audio_path.write_bytes(segment.data)
        else:
            raise LifecycleError(f"empty audio for chunk {entry.id}")
        mark_completed(manifest, entry.id, rel)
        save_manifest(manifest, book.manifest_path)
        _notify(progress_callback, "tts-persist", entry.id)
    return _segments_from_manifest(book)


def _segments_from_manifest(book: BookWorkLayout) -> list[AudioSegment]:
    from audiobook_ai.state.manifest import completed_audio_segments

    manifest = load_manifest(book.manifest_path)
    segments: list[AudioSegment] = []
    for entry, path in completed_audio_segments(manifest, book_root=book.root):
        segments.append(
            AudioSegment(
                path=path,
                format="wav",
                chapter_id=str(entry.metadata.get("chapter_id"))
                if entry.metadata.get("chapter_id")
                else None,
                segment_index=entry.sequence,
            )
        )
    return segments


def _notify(
    callback: ProgressCallback | None,
    stage: str,
    detail: str,
) -> None:
    if callback is not None:
        callback(stage, detail)


def default_worker_spawn_success(provider_free: Callable[[], None] | None = None) -> SpawnFn:
    """Factory for tests: pretend workers succeed and free VRAM."""

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        if provider_free is not None:
            provider_free()
        return CompletedProcessLike(returncode=0)


# ---------------------------------------------------------------------------
# Multi-worker chunk distributor
# ---------------------------------------------------------------------------

def distribute_chunks_by_voice_round_robin(
    chunks: list,
    worker_count: int,
) -> dict[int, list]:
    """Distribute *chunks* across *worker_count* workers via round-robin on voice_id.

    Each chunk's ``metadata`` must contain ``voice_id`` (or defaults to narrator).
    Returns ``{worker_id: [chunk, …]}`` with keys 0..worker_count-1.
    """
    buckets: dict[int, list] = {wid: [] for wid in range(worker_count)}
    for chunk in chunks:
        voice_id = chunk.metadata.get("voice_id") or config.NARRATOR_VOICE_ID
        worker_id = hash(str(voice_id)) % worker_count
        buckets[worker_id].append(chunk.id)
    return buckets


def resolve_tts_workers(
    book: BookWorkLayout,
    worker_count: int,
) -> dict[int, list[str]]:
    """Return pending chunk-id subsets keyed by worker_id.

    Reads the manifest, filters pending chunks, and distributes via
    :func:`distribute_chunks_by_voice_round_robin`.
    """
    manifest = load_manifest(book.manifest_path)
    pending = pending_chunks(manifest, book_root=book.root)
    if not pending:
        return {wid: [] for wid in range(worker_count)}
    buckets = distribute_chunks_by_voice_round_robin(pending, worker_count)
    # Convert to chunk ids only (worker subprocess re-reads manifest)
    return {wid: chunk_ids for wid, chunk_ids in buckets.items()}
