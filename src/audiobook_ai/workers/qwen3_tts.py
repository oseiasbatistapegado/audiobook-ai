"""Qwen3-TTS worker: load once → SpeechChunks → persist → reclaim → exit.

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
from audiobook_ai.tts.qwen3_tts import Qwen3TTSBackend
from audiobook_ai.utils.logging import get_logger, setup_logging
from audiobook_ai.weights.manager import ModelManager

logger = get_logger(__name__)

# Architectural backend id for guardian / jobs (concrete model is qwen3-tts).
TTS_BACKEND_ID = "tts"


def _best_effort_reclaim(tts: Qwen3TTSBackend, guardian: VRAMGuardian):
    """Drop transient caches without unloading the engine; return snapshot."""
    del tts  # reclaim is process-wide; engine stays resident
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:  # noqa: BLE001
        logger.debug("torch reclaim failed", exc_info=True)
    snap = guardian.snapshot()
    guardian.log_event("after_reclaim", backend=TTS_BACKEND_ID, snap=snap)
    return snap


def run_qwen3_tts_job(
    job_dir: Path,
    *,
    tts: Qwen3TTSBackend | None = None,
    guardian: VRAMGuardian | None = None,
) -> int:
    """Execute a Qwen3-TTS job; return process exit code."""
    job = read_job(job_dir)
    if job.backend not in {TTS_BACKEND_ID, "qwen3-tts"}:
        write_result(
            job_dir,
            JobResult(
                job_id=job.job_id,
                exit_code=int(WorkerExitCode.FATAL),
                message=f"unexpected backend={job.backend!r} for qwen3-tts worker",
            ),
        )
        return int(WorkerExitCode.FATAL)

    # Worker-aware logger: prefix all logs with worker_id for multi-worker mode.
    worker_id = job.worker_id
    if worker_id is not None:
        import logging

        class WorkerPrefixAdapter(logging.LoggerAdapter):
            def process(self, msg, kwargs):  # type: ignore[override]
                return f"[gpu] worker={worker_id} {msg}", kwargs

        worker_logger = WorkerPrefixAdapter(logger, {})
    else:
        worker_logger = logger  # single-worker: same logger

    book_root = Path(job.book_root)
    manifest_path = Path(job.manifest_path)
    manifest = load_manifest(manifest_path)
    worker_logger.info(
        "start worker_id=%d job_id=%s pending=%d",
        worker_id,
        job.job_id,
        len(job.pending_chunk_ids),
    )

    load_target = (
        job.config.before_load_target_mib
        or config.TTS_BEFORE_LOAD_TARGET_MIB
    )
    cfg = GuardianConfig(
        hard_floor_mib=job.config.hard_floor_mib,
        before_chunk_target_mib=job.config.before_chunk_target_mib,
        load_targets_mib={
            TTS_BACKEND_ID: load_target,
            "qwen3-tts": load_target,
            "parler": config.PARLER_BEFORE_LOAD_TARGET_MIB,
        },
        progressive_window_k=job.config.progressive_window_k,
        progressive_drop_mib=job.config.progressive_drop_mib,
        progressive_allocated_growth_mib=job.config.progressive_allocated_growth_mib,
        progressive_floor_margin_mib=job.config.progressive_floor_margin_mib,
    )
    g = guardian or VRAMGuardian(SystemMemoryProvider(), cfg=cfg)

    apply_process_vram_reserve(config.GPU_PROCESS_RESERVE_MIB)

    try:
        g.require_safe_headroom(kind="load", backend=TTS_BACKEND_ID)
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

    backend = tts or Qwen3TTSBackend(
        manager=ModelManager(cache_dir=job.config.cache_dir),
        output_dir=book_root / config.AUDIO_SUBDIR,
        cache_dir=job.config.cache_dir,
    )
    backend.book_id = job.book_id
    backend.ensure_ready(load_engine=True)
    g.log_event("load", backend=TTS_BACKEND_ID)

    completed: list[str] = []
    pending_ids = list(job.pending_chunk_ids) or [
        e.id for e in manifest.ordered_chunks() if e.status.value != "completed"
    ]
    batch_limit = max(
        1,
        job.config.tts_same_voice_batch_size
        or config.TTS_SAME_VOICE_BATCH_SIZE,
    )

    def _request_for(entry: object) -> TTSRequest:
        emotion_raw = entry.metadata.get("emotion", "neutral")  # type: ignore[attr-defined]
        try:
            emotion = Emotion(emotion_raw)
        except ValueError:
            emotion = Emotion.NEUTRAL
        voice_id = entry.metadata.get("voice_id") or config.NARRATOR_VOICE_ID  # type: ignore[attr-defined]
        return TTSRequest(
            text=entry.text,  # type: ignore[attr-defined]
            voice_id=str(voice_id),
            emotion=emotion,
            chapter_id=str(entry.metadata.get("chapter_id") or "chapter"),  # type: ignore[attr-defined]
            segment_index=entry.sequence,  # type: ignore[attr-defined]
        )

    try:
        cursor = 0
        while cursor < len(pending_ids):
            lead_id = pending_ids[cursor]
            lead = manifest.get(lead_id)
            if lead is None:
                cursor += 1
                continue

            snap = _best_effort_reclaim(backend, g)
            g.log_event(
                "before_chunk",
                backend=TTS_BACKEND_ID,
                chunk_id=lead_id,
                snap=snap,
            )

            ok, reason = g.can_start_chunk(snap)
            if not ok:
                save_manifest(manifest, manifest_path)
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED),
                        message=f"chunk gate failed before {lead_id}: {reason}",
                        completed_chunk_ids=completed,
                        restart_reason="headroom",
                    ),
                )
                return int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)

            lead_voice = str(
                lead.metadata.get("voice_id") or config.NARRATOR_VOICE_ID
            )
            residency_cap = (
                job.config.tts_chunks_per_worker
                if job.config.tts_chunks_per_worker
                else job.config.fish_chunks_per_worker
            )
            max_batch = batch_limit
            if residency_cap > 0:
                remaining = max(1, residency_cap - len(completed))
                max_batch = min(max_batch, remaining)
            batch_entries = [lead]
            look = cursor + 1
            while look < len(pending_ids) and len(batch_entries) < max_batch:
                nxt = manifest.get(pending_ids[look])
                if nxt is None:
                    look += 1
                    continue
                nxt_voice = str(
                    nxt.metadata.get("voice_id") or config.NARRATOR_VOICE_ID
                )
                if nxt_voice != lead_voice:
                    break
                batch_entries.append(nxt)
                look += 1

            # CPU prep of TTSRequests before GPU generate (same-voice batch).
            batch_requests = [_request_for(e) for e in batch_entries]
            batch_ids = [e.id for e in batch_entries]
            try:
                segments = backend.synthesize_batch(batch_requests)
            except Exception as exc:  # noqa: BLE001
                if is_cuda_oom(exc):
                    save_manifest(manifest, manifest_path)
                    g.log_event(
                        "unexpected_oom",
                        backend=TTS_BACKEND_ID,
                        chunk_id=lead_id,
                    )
                    write_result(
                        job_dir,
                        JobResult(
                            job_id=job.job_id,
                            exit_code=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED),
                            message=(
                                f"unexpected_oom before/during {lead_id}: {exc}; "
                                "worker exit for hard reclaim (not normal control flow)"
                            ),
                            completed_chunk_ids=completed,
                            restart_reason="oom",
                            oom_chunk_id=lead_id,
                        ),
                    )
                    return int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
                mark_failed(manifest, lead_id, str(exc))
                save_manifest(manifest, manifest_path)
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.FATAL),
                        message=str(exc),
                        completed_chunk_ids=completed,
                        failed_chunk_id=lead_id,
                    ),
                )
                return int(WorkerExitCode.FATAL)

            if len(segments) != len(batch_entries):
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.FATAL),
                        message=(
                            f"batch size mismatch ids={batch_ids} "
                            f"segments={len(segments)}"
                        ),
                        completed_chunk_ids=completed,
                        failed_chunk_id=lead_id,
                    ),
                )
                return int(WorkerExitCode.FATAL)

            for entry, segment in zip(batch_entries, segments, strict=True):
                chunk_id = entry.id
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

                # Persist-before-reclaim: mark each chunk completed before next.
                mark_completed(manifest, chunk_id, rel, worker_id=job.worker_id)
                save_manifest(manifest, manifest_path)
                completed.append(chunk_id)

            snap_after = _best_effort_reclaim(backend, g)
            if g.record_post_reclaim(snap_after):
                write_result(
                    job_dir,
                    JobResult(
                        job_id=job.job_id,
                        exit_code=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED),
                        message=f"progressive growth after {batch_ids[-1]}",
                        completed_chunk_ids=completed,
                        restart_reason="progressive",
                    ),
                )
                return int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)

            residency_cap = (
                job.config.tts_chunks_per_worker
                if job.config.tts_chunks_per_worker
                else job.config.fish_chunks_per_worker
            )
            cursor = look
            if (
                residency_cap > 0
                and len(completed) >= residency_cap
                and cursor < len(pending_ids)
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
            worker_logger.debug("qwen3-tts worker release failed", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qwen3-TTS GPU worker")
    parser.add_argument("job_dir", type=Path, help="Path to versioned job directory")
    args = parser.parse_args(argv)
    log_path = Path(args.job_dir) / "worker.log"
    setup_logging(log_file=log_path)
    return run_qwen3_tts_job(args.job_dir)


if __name__ == "__main__":
    sys.exit(main())
