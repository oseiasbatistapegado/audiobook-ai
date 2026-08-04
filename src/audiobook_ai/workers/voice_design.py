"""Voice Design worker: load Parler → batch missing voices → unload → exit.

Hard reclaim between Voice Design and TTS is process exit, verified
by the orchestrator's LifecycleManager.

This worker SHOULD run under the Parler-isolated interpreter
(``.venv-parler`` / ``AUDIOBOOK_AI_VOICE_DESIGN_PYTHON``) because Parler
requires ``transformers==4.46.1``, incompatible with ``qwen-tts``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.gpu.jobs import (
    JobResult,
    WorkerExitCode,
    read_job,
    write_result,
)
from audiobook_ai.gpu.memory import apply_process_vram_reserve
from audiobook_ai.state.store import load_story_state, save_story_state
from audiobook_ai.state.voices import ensure_voices_batch
from audiobook_ai.utils.logging import get_logger, setup_logging
from audiobook_ai.voice.generator import get_voice_generator

logger = get_logger(__name__)


def run_voice_design_job(job_dir: Path) -> int:
    """Execute a voice-design job directory; return process exit code."""
    job = read_job(job_dir)
    if job.backend != "parler":
        write_result(
            job_dir,
            JobResult(
                job_id=job.job_id,
                exit_code=int(WorkerExitCode.FATAL),
                message=f"unexpected backend={job.backend!r} for voice-design worker",
            ),
        )
        return int(WorkerExitCode.FATAL)

    apply_process_vram_reserve(config.GPU_PROCESS_RESERVE_MIB)

    book_root = Path(job.book_root)
    story_path = book_root / "story.json"
    story = load_story_state(story_path) if story_path.is_file() else None
    if story is None:
        from audiobook_ai.models.story import StoryState

        story = StoryState()

    generator = get_voice_generator(
        job.config.extra.get("generator_name"),
        # registry created inside ensure_voices_batch
    )
    try:
        ensure_voices_batch(
            story,
            list(job.character_ids),
            book_id=job.book_id,
            cache_root=job.config.cache_dir,
            generator=generator,
        )
        save_story_state(story, story_path)
        write_result(
            job_dir,
            JobResult(
                job_id=job.job_id,
                exit_code=int(WorkerExitCode.SUCCESS),
                message=f"generated/ensured {len(job.character_ids)} characters",
            ),
        )
        return int(WorkerExitCode.SUCCESS)
    except Exception as exc:  # noqa: BLE001 — worker boundary
        logger.exception("voice-design worker failed")
        unload = getattr(generator, "unload", None)
        if callable(unload):
            try:
                unload()
            except Exception:  # noqa: BLE001
                logger.debug("voice-design unload after failure failed", exc_info=True)
        write_result(
            job_dir,
            JobResult(
                job_id=job.job_id,
                exit_code=int(WorkerExitCode.FATAL),
                message=str(exc),
            ),
        )
        return int(WorkerExitCode.FATAL)
    finally:
        # Best-effort in-process unload; hard reclaim is process exit.
        unload = getattr(generator, "unload", None)
        if callable(unload):
            try:
                unload()
            except Exception:  # noqa: BLE001
                logger.debug("voice-design unload failed", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voice Design GPU worker")
    parser.add_argument("job_dir", type=Path, help="Path to versioned job directory")
    args = parser.parse_args(argv)
    setup_logging(log_file=Path(args.job_dir) / "worker.log")
    return run_voice_design_job(args.job_dir)


if __name__ == "__main__":
    sys.exit(main())
