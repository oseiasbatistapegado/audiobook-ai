"""Versioned job-directory IPC between orchestrator and GPU workers."""

from __future__ import annotations

import json
import os
import tempfile
from enum import IntEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from audiobook_ai import config

JOB_SCHEMA_VERSION = 1


class WorkerExitCode(IntEnum):
    """Authoritative worker outcomes (stdout/stderr are diagnostic only)."""

    SUCCESS = 0
    CONTROLLED_RESTART_NEEDED = 10
    FATAL = 20


class JobConfig(BaseModel):
    hard_floor_mib: int = config.HARD_FLOOR_MIB
    before_chunk_target_mib: int = config.BEFORE_CHUNK_TARGET_MIB
    before_load_target_mib: int | None = None
    tts_max_chunk_chars: int = config.TTS_MAX_CHUNK_CHARS
    progressive_window_k: int = config.PROGRESSIVE_GROWTH_WINDOW_K
    progressive_drop_mib: int = config.PROGRESSIVE_GROWTH_DROP_MIB
    progressive_allocated_growth_mib: int = config.PROGRESSIVE_ALLOCATED_GROWTH_MIB
    progressive_floor_margin_mib: int = config.PROGRESSIVE_FLOOR_MARGIN_MIB
    # 0 = guardian-driven only; >0 = optional residency ceiling escape hatch.
    tts_chunks_per_worker: int = config.TTS_CHUNKS_PER_WORKER
    # Legacy alias (read by older job.json / until tests catch up).
    fish_chunks_per_worker: int = config.TTS_CHUNKS_PER_WORKER
    # Max SpeechChunks sharing a voice_id to submit in one generate call.
    tts_same_voice_batch_size: int = config.TTS_SAME_VOICE_BATCH_SIZE
    cache_dir: str | None = None
    # Concrete TTS model logical id (qwen3-tts).
    tts_logical_id: str | None = None
    # Legacy Fish fields kept for job.json back-compat during migration.
    fish_model_alias: str | None = None
    fish_logical_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class JobDefinition(BaseModel):
    """Canonical job file written under ``work/<book_id>/jobs/<job_id>/``."""

    version: int = JOB_SCHEMA_VERSION
    job_id: str
    backend: str
    book_id: str
    book_root: str
    manifest_path: str
    pending_chunk_ids: list[str] = Field(default_factory=list)
    # Voice-design jobs: character ids to generate.
    character_ids: list[str] = Field(default_factory=list)
    # Multi-worker TTS: which worker this job belongs to (0-based index).
    worker_id: int | None = None
    config: JobConfig = Field(default_factory=JobConfig)
    inputs: dict[str, Any] = Field(default_factory=dict)


class JobResult(BaseModel):
    version: int = JOB_SCHEMA_VERSION
    job_id: str
    exit_code: int
    message: str | None = None
    completed_chunk_ids: list[str] = Field(default_factory=list)
    failed_chunk_id: str | None = None
    # When exit_code is CONTROLLED_RESTART_NEEDED: why.
    # Planned reclaim (progressive / headroom / residency) MUST NOT charge
    # OOM/stall gates. ``oom`` and unknown reasons MUST charge them.
    restart_reason: str | None = None
    # When restart_reason is ``oom``: SpeechChunk id that triggered unexpected OOM.
    oom_chunk_id: str | None = None


# Restart reasons that are healthy hard-reclaim (do not charge OOM/stall gates).
PLANNED_RESTART_REASONS: frozenset[str] = frozenset(
    {"progressive", "headroom", "residency"}
)


def job_dir(book_jobs_root: Path, job_id: str) -> Path:
    return Path(book_jobs_root) / job_id


def job_definition_path(directory: Path) -> Path:
    return Path(directory) / "job.json"


def job_result_path(directory: Path) -> Path:
    return Path(directory) / "result.json"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".job-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_job(directory: Path, job: JobDefinition) -> Path:
    path = job_definition_path(directory)
    write_json_atomic(path, job.model_dump(mode="json"))
    return path


def read_job(directory: Path) -> JobDefinition:
    path = job_definition_path(directory)
    data = json.loads(path.read_text(encoding="utf-8"))
    return JobDefinition.model_validate(data)


def write_result(directory: Path, result: JobResult) -> Path:
    path = job_result_path(directory)
    write_json_atomic(path, result.model_dump(mode="json"))
    return path


def read_result(directory: Path) -> JobResult | None:
    path = job_result_path(directory)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return JobResult.model_validate(data)
