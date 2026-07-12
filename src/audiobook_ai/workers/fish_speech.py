"""Fish Speech worker: load once → SpeechChunks → persist → reclaim → exit.

Exit codes:
- SUCCESS (0)
- CONTROLLED_RESTART_NEEDED (10) — headroom/progressive growth; orchestrator retries
- FATAL (20)
"""

from __future__ import annotations

import argparse
import gc
import sys
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.gpu.guardian import (
    GuardianConfig,
    MemoryPolicyError,
    VRAMGuardian,
)
from audiobook_ai.gpu.jobs import (
    JobResult,
    WorkerExitCode,
    read_job,
    write_result,
)
from audiobook_ai.gpu.memory import SystemMemoryProvider, apply_process_vram_reserve, is_cuda_oom
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.state.manifest import (
    load_manifest,
    mark_completed,
    mark_failed,
    relative_audio_path,
    save_manifest,
)
from audiobook_ai.tts.fish_speech import FishSpeechBackend
from audiobook_ai.utils.logging import get_logger, setup_logging
from audiobook_ai.weights.manager import ModelManager

logger = get_logger(__name__)


def _best_effort_reclaim(tts: FishSpeechBackend, guardian: VRAMGuardian) -> float | None:
    """Drop transient caches without unloading the engine; return free_mib."""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:  # noqa: BLE001
        logger.debug("torch reclaim failed", exc_info=True)
    # Soft reclaim only — engine stays loaded inside this worker.
    snap = guardian.snapshot()
    guardian.log_event("after_reclaim", backend="fish-speech", snap=snap)
    return snap.free_mib


def run_fish_speech_job(
    job_dir: Path,
    *,
    tts: FishSpeechBackend | None = None,
    guardian: VRAMGuardian | None = None,
) -> int:
    """Execute a Fish Speech job; return process exit code."""
    job = read_job(job_dir)
    if job.backend != "fish-speech":
        write_result(
            job_dir,
            JobResult(
                job_id=job.job_id,
                exit_code=int(WorkerExitCode.FATAL),
                message=f"unexpected backend={job.backend!r} for fish worker",
            ),
        )
        return int(WorkerExitCode.FATAL)

    book_root = Path(job.book_root)
    manifest_path = Path(job.manifest_path)
    manifest = load_manifest(manifest_path)

    cfg = GuardianConfig(
        hard_floor_mib=job.config.hard_floor_mib,
        before_chunk_target_mib=job.config.before_chunk_target_mib,
        load_targets_mib={
            "fish-speech": job.config.before_load_target_mib
            or config.FISH_BEFORE_LOAD_TARGET_MIB,
            "parler": config.PARLER_BEFORE_LOAD_TARGET_MIB,
        },
        progressive_window_k=job.config.progressive_window_k,
        progressive_drop_mib=job.config.progressive_drop_mib,
    )
    g = guardian or VRAMGuardian(SystemMemoryProvider(), cfg=cfg)

    # Cap allocator before load so synth peaks OOM the worker, not Hyprland.
    apply_process_vram_reserve(config.GPU_PROCESS_RESERVE_MIB)

    try:
        g.require_safe_headroom(kind="load", backend="fish-speech")
    except MemoryPolicyError as exc:
        write_result(
            job_dir,
            JobResult(
                job_id=job.job_id,
                exit_code=int(WorkerExitCode.FATAL),
                message=str(exc),
            ),
        )
        return int(WorkerExitCode.FATAL)

    backend = tts or FishSpeechBackend(
        manager=ModelManager(cache_dir=job.config.cache_dir),
        output_dir=book_root / config.AUDIO_SUBDIR,
        cache_dir=job.config.cache_dir,
        fish_model=job.config.fish_model_alias,
        fish_logical_id=job.config.fish_logical_id,
    )
    backend.book_id = job.book_id
    backend.ensure_ready(load_engine=True)
    g.log_event("load", backend="fish-speech")

    completed: list[str] = []
    pending_ids = list(job.pending_chunk_ids) or [
        e.id for e in manifest.ordered_chunks() if e.status.value != "completed"
    ]

    try:
        for chunk_id in pending_ids:
            entry = manifest.get(chunk_id)
            if entry is None:
                continue

            free = _best_effort_reclaim(backend, g)
            snap = g.snapshot()
            g.log_event("before_chunk", backend="fish-speech", chunk_id=chunk_id, snap=snap)

            ok, reason = g.can_start_chunk(snap)
            if not ok:
                # Never wait for hard floor / OOM to prove degradation.
                save_manifest(manifest, manifest_path)
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED),
                        message=f"chunk gate failed before {chunk_id}: {reason}",
                        completed_chunk_ids=completed,
                        restart_reason="headroom",
                    ),
                )
                return int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)

            emotion_raw = entry.metadata.get("emotion", "neutral")
            try:
                emotion = Emotion(emotion_raw)
            except ValueError:
                emotion = Emotion.NEUTRAL

            voice_id = entry.metadata.get("voice_id") or config.NARRATOR_VOICE_ID
            request = TTSRequest(
                text=entry.text,
                voice_id=str(voice_id),
                emotion=emotion,
                chapter_id=str(entry.metadata.get("chapter_id") or "chapter"),
                segment_index=entry.sequence,
            )
            try:
                segment = backend.synthesize(request)
            except Exception as exc:  # noqa: BLE001
                if is_cuda_oom(exc):
                    # Leave chunk pending for a fresh worker. Do NOT set
                    # failed_chunk_id or mark_failed — those burn hard per-chunk
                    # attempts; OOM retries are gated by stall / per-chunk OOM.
                    save_manifest(manifest, manifest_path)
                    g.log_event("unexpected_oom", backend="fish-speech", chunk_id=chunk_id)
                    write_result(
                        job_dir,
                        JobResult(
                            job_id=job.job_id,
                            exit_code=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED),
                            message=(
                                f"unexpected_oom before/during {chunk_id}: {exc}; "
                                "worker exit for hard reclaim (not normal control flow)"
                            ),
                            completed_chunk_ids=completed,
                            restart_reason="oom",
                            oom_chunk_id=chunk_id,
                        ),
                    )
                    return int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
                mark_failed(manifest, chunk_id, str(exc))
                save_manifest(manifest, manifest_path)
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.FATAL),
                        message=str(exc),
                        completed_chunk_ids=completed,
                        failed_chunk_id=chunk_id,
                    ),
                )
                return int(WorkerExitCode.FATAL)

            rel = relative_audio_path(entry.sequence)
            audio_path = book_root / rel
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            if segment.path is not None and segment.path.is_file():
                if segment.path.resolve() != audio_path.resolve():
                    audio_path.write_bytes(segment.path.read_bytes())
            elif segment.data:
                audio_path.write_bytes(segment.data)
            else:
                mark_failed(manifest, chunk_id, "empty audio")
                save_manifest(manifest, manifest_path)
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.FATAL),
                        message=f"empty audio for {chunk_id}",
                        completed_chunk_ids=completed,
                        failed_chunk_id=chunk_id,
                    ),
                )
                return int(WorkerExitCode.FATAL)

            # Persist before reclaim (resume contract).
            mark_completed(manifest, chunk_id, rel)
            save_manifest(manifest, manifest_path)
            completed.append(chunk_id)

            free_after = _best_effort_reclaim(backend, g)
            if free_after is not None and g.record_post_reclaim(free_after):
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED),
                        message=f"progressive growth after {chunk_id}",
                        completed_chunk_ids=completed,
                        restart_reason="progressive",
                    ),
                )
                return int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)

            # Optional residency ceiling (escape hatch). Primary reclaim is
            # guardian-driven; 0 / unset disables calendar EXIT.
            residency_cap = job.config.fish_chunks_per_worker
            if (
                residency_cap > 0
                and len(completed) >= residency_cap
                and pending_ids[pending_ids.index(chunk_id) + 1 :]
            ):
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED),
                        message=(
                            f"residency cap after {len(completed)} chunks "
                            f"(limit={residency_cap})"
                        ),
                        completed_chunk_ids=completed,
                        restart_reason="residency",
                    ),
                )
                return int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)

        write_result(
            job_dir,
            JobResult(
                job_id=job.job_id,
                exit_code=int(WorkerExitCode.SUCCESS),
                message=f"completed {len(completed)} chunks",
                completed_chunk_ids=completed,
            ),
        )
        return int(WorkerExitCode.SUCCESS)
    finally:
        try:
            backend.release()
        except Exception:  # noqa: BLE001
            logger.debug("fish worker release failed", exc_info=True)
        # Hard reclaim is process exit.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fish Speech GPU worker")
    parser.add_argument("job_dir", type=Path, help="Path to versioned job directory")
    args = parser.parse_args(argv)
    log_path = Path(args.job_dir) / "worker.log"
    setup_logging(log_file=log_path)
    return run_fish_speech_job(args.job_dir)


if __name__ == "__main__":
    sys.exit(main())
