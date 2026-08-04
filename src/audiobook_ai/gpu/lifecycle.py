"""LifecycleManager: exclusive GPU worker lease, spawn/join, verify release."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.gpu.guardian import MemoryPolicyError, VRAMGuardian
from audiobook_ai.gpu.jobs import WorkerExitCode
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

ProgressCallback = Callable[[str, str], None]

_EXPANDABLE_SEGMENTS = "expandable_segments:True"
_ALLOC_CONF_KEYS = ("PYTORCH_HIP_ALLOC_CONF", "PYTORCH_CUDA_ALLOC_CONF")


def merge_pytorch_alloc_conf(
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return env with expandable_segments set unless the user already overrode.

    Prefer HIP alloc conf on ROCm; also set CUDA alloc conf when unset (HIP
    stacks sometimes honor the CUDA variable name). Scrubs host PYTHONPATH so
    isolated worker venvs are not shadowed by Nix/direnv.
    """
    from audiobook_ai.gpu.runtimes import worker_env as scrubbed_worker_env

    env = scrubbed_worker_env(base=base_env)
    for key in _ALLOC_CONF_KEYS:
        existing = env.get(key)
        if existing is None or not str(existing).strip():
            env[key] = _EXPANDABLE_SEGMENTS
    return env


class LifecycleError(RuntimeError):
    """Worker lifecycle failure."""


class WorkerLeaseBusyError(LifecycleError):
    """Raised when a second GPU worker is requested while one is active."""


@dataclass(slots=True)
class WorkerResult:
    backend: str
    exit_code: int
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    killed: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == int(WorkerExitCode.SUCCESS) and not self.timed_out

    @property
    def controlled_restart_needed(self) -> bool:
        return self.returncode == int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)


SpawnFn = Callable[[Sequence[str], Path | None], "CompletedProcessLike"]


class CompletedProcessLike:
    def __init__(
        self,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class MultiWorkerError(LifecycleError):
    """Raised when multi-worker operations conflict with single-worker lease."""


class LifecycleManager:
    """Ensure at most one project-controlled GPU worker (or set of multi-workers) is active."""

    def __init__(
        self,
        guardian: VRAMGuardian | None = None,
        *,
        default_timeout_s: float = 3600.0,
        spawn_fn: SpawnFn | None = None,
    ) -> None:
        self.guardian = guardian or VRAMGuardian()
        self.default_timeout_s = default_timeout_s
        self._spawn_fn = spawn_fn
        self._active_backend: str | None = None
        self._active_proc: subprocess.Popen[str] | None = None
        # Multi-worker state: {worker_id: Popen}
        self._multi_workers: dict[int, subprocess.Popen[str]] = {}

    @property
    def active_backend(self) -> str | None:
        return self._active_backend

    def run_worker(
        self,
        backend: str,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout_s: float | None = None,
        verify_release: bool = True,
        release_target_mib: float | None = None,
        next_backend_for_release: str | None = None,
        progress_callback: ProgressCallback | None = None,
        skip_load_gate: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> WorkerResult:
        """Spawn a GPU worker under the exclusive lease and verify release."""
        if self._active_backend is not None:
            raise WorkerLeaseBusyError(
                f"GPU lease busy with backend={self._active_backend}; "
                f"refusing to start {backend}"
            )
        if self._multi_workers:
            raise WorkerLeaseBusyError(
                f"{len(self._multi_workers)} multi-worker(s) active; "
                f"refusing to start single worker {backend}"
            )

        if not skip_load_gate:
            self.guardian.require_safe_headroom(kind="load", backend=backend)
        self.guardian.log_event("load", backend=backend)
        self._notify(progress_callback, "gpu-worker", f"spawn {backend}")

        self._active_backend = backend
        timeout = self.default_timeout_s if timeout_s is None else timeout_s
        timed_out = False
        killed = False
        stdout = ""
        stderr = ""
        returncode = int(WorkerExitCode.FATAL)
        spawn_env = dict(env) if env is not None else None
        if spawn_env is None:
            from audiobook_ai.gpu.runtimes import worker_env as scrubbed_worker_env

            spawn_env = scrubbed_worker_env()

        try:
            if self._spawn_fn is not None:
                completed = self._spawn_fn(command, cwd)
                returncode = completed.returncode
                stdout = completed.stdout or ""
                stderr = completed.stderr or ""
            else:
                proc = subprocess.Popen(
                    list(command),
                    cwd=str(cwd) if cwd is not None else None,
                    env=spawn_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self._active_proc = proc
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                    returncode = proc.returncode if proc.returncode is not None else -1
                except subprocess.TimeoutExpired:
                    timed_out = True
                    proc.kill()
                    stdout, stderr = proc.communicate(timeout=30)
                    returncode = proc.returncode if proc.returncode is not None else -1
                    killed = True
                    raise LifecycleError(
                        f"worker backend={backend} timed out after {timeout}s"
                    ) from None
        finally:
            self._active_proc = None
            self._active_backend = None
            self._notify(progress_callback, "gpu-worker", f"exit {backend} code={returncode}")
            self.guardian.log_event("worker_exit", backend=backend)

            if verify_release:
                target_backend = next_backend_for_release or backend
                target = release_target_mib
                if target is None:
                    loaded = self.guardian.cfg.load_target_for(target_backend)
                    # After Voice Design, verify against next TTS load target when known.
                    # After TTS, require TTS load-target reclaim so the next chapter
                    # (Ollama → TTS) is not gated on a stale partial free snapshot.
                    if loaded is not None and (
                        next_backend_for_release is not None or backend in {"tts", "qwen3-tts", "fish-speech"}
                    ):
                        target = float(loaded)
                    else:
                        target = float(self.guardian.cfg.hard_floor_mib)
                try:
                    self.guardian.wait_until_free(
                        float(target),
                        backend=backend,
                        event="wait_release",
                    )
                    self.guardian.require_safe_headroom(
                        kind="release",
                        backend=backend,
                        release_target_mib=target,
                    )
                    self.guardian.log_event("release_verified", backend=backend)
                    self._notify(progress_callback, "vram-handoff", f"release-verified {backend}")
                except MemoryPolicyError:
                    self.guardian.log_event("release_failed", backend=backend)
                    self._notify(progress_callback, "vram-handoff", f"release-failed {backend}")
                    raise

            # Surface worker [gpu] telemetry from stderr into the orchestrator log.
            for stream_name, text in (("stdout", stdout), ("stderr", stderr)):
                if not text:
                    continue
                for line in text.splitlines():
                    if "[gpu]" in line:
                        logger.info("worker_%s %s", stream_name, line.strip())

        return WorkerResult(
            backend=backend,
            exit_code=returncode,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            killed=killed,
        )

    def run_tts_with_restarts(
        self,
        command_factory: Callable[[], Sequence[str]],
        *,
        cwd: Path | None = None,
        restart_budget: int | None = None,
        has_pending: Callable[[], bool],
        progress_callback: ProgressCallback | None = None,
        skip_load_gate: bool = False,
        counts_against_budget: Callable[[WorkerResult], bool] | None = None,
        restart_reason_fn: Callable[[WorkerResult], str | None] | None = None,
        completed_count: Callable[[], int] | None = None,
        oom_chunk_id_fn: Callable[[WorkerResult], str | None] | None = None,
        no_progress_limit: int | None = None,
        chunk_max_oom_attempts: int | None = None,
        worker_env: Mapping[str, str] | None = None,
    ) -> WorkerResult:
        """Run TTS worker, restarting on controlled_restart_needed with OOM gates.

        Primary abort gates (charged restarts only: OOM / unknown):

        - ``TTS_OOM_NO_PROGRESS_LIMIT`` consecutive charged restarts with no
          new completed SpeechChunks (stall).
        - ``TTS_CHUNK_MAX_OOM_ATTEMPTS`` OOMs for the same ``oom_chunk_id``.

        ``restart_budget`` / ``TTS_WORKER_RESTART_BUDGET`` is an optional hard
        cap; ``0`` disables it. Planned reclaim
        (``progressive`` / ``headroom`` / ``residency``) SHOULD be excluded via
        ``counts_against_budget`` so long books are not aborted.
        """
        budget = (
            config.TTS_WORKER_RESTART_BUDGET
            if restart_budget is None
            else restart_budget
        )
        stall_limit = (
            config.TTS_OOM_NO_PROGRESS_LIMIT
            if no_progress_limit is None
            else no_progress_limit
        )
        per_chunk_limit = (
            config.TTS_CHUNK_MAX_OOM_ATTEMPTS
            if chunk_max_oom_attempts is None
            else chunk_max_oom_attempts
        )
        tts_env = (
            dict(worker_env)
            if worker_env is not None
            else merge_pytorch_alloc_conf()
        )
        charged_restarts = 0
        stall_count = 0
        oom_by_chunk: dict[str, int] = {}
        baseline_completed = completed_count() if completed_count is not None else 0
        last: WorkerResult | None = None
        while True:
            cmd = command_factory()
            last = self.run_worker(
                "tts",
                cmd,
                cwd=cwd,
                progress_callback=progress_callback,
                skip_load_gate=skip_load_gate,
                verify_release=True,
                env=tts_env,
            )
            if last.success:
                return last
            if last.controlled_restart_needed and has_pending():
                charge = True
                if counts_against_budget is not None:
                    charge = counts_against_budget(last)
                reason = None
                if restart_reason_fn is not None:
                    reason = restart_reason_fn(last)
                reason_label = reason or "unknown"

                if completed_count is not None:
                    now_completed = completed_count()
                    if now_completed > baseline_completed:
                        stall_count = 0
                        baseline_completed = now_completed

                if charge:
                    chunk_id = None
                    if oom_chunk_id_fn is not None:
                        chunk_id = oom_chunk_id_fn(last)
                    if chunk_id:
                        oom_by_chunk[chunk_id] = oom_by_chunk.get(chunk_id, 0) + 1
                        if oom_by_chunk[chunk_id] >= per_chunk_limit:
                            raise LifecycleError(
                                f"TTS worker OOM limit for chunk {chunk_id} "
                                f"exhausted ({per_chunk_limit}); refusing further "
                                "controlled restarts"
                            )

                    stall_count += 1
                    if stall_count >= stall_limit:
                        raise LifecycleError(
                            f"TTS worker OOM stall: {stall_count} charged restarts "
                            f"without progress (limit={stall_limit}); refusing "
                            "further controlled restarts"
                        )

                    if budget > 0:
                        if charged_restarts >= budget:
                            raise LifecycleError(
                                f"TTS worker restart budget exhausted ({budget}); "
                                "refusing further controlled restarts"
                            )
                        charged_restarts += 1
                        detail = (
                            f"controlled-restart tts {reason_label} "
                            f"{charged_restarts}/{budget}"
                        )
                    else:
                        charged_restarts += 1
                        detail = (
                            f"controlled-restart tts {reason_label} "
                            f"charged={charged_restarts} stall={stall_count}/"
                            f"{stall_limit}"
                        )
                else:
                    detail = (
                        f"controlled-restart tts {reason_label} (no budget)"
                    )
                self._notify(progress_callback, "gpu-worker", detail)
                logger.info(
                    "[gpu] event=controlled_restart backend=tts "
                    "reason=%s charged_restarts=%s budget=%s charged=%s "
                    "stall=%s",
                    reason_label,
                    charged_restarts,
                    budget,
                    charge,
                    stall_count,
                )
                time.sleep(0.05)
                continue
            return last

    # Back-compat alias until call sites / tests fully migrate.
    run_fish_with_restarts = run_tts_with_restarts

    # ------------------------------------------------------------------
    # Multi-worker helpers
    # ------------------------------------------------------------------

    @property
    def multi_worker_pids(self) -> dict[int, subprocess.Popen[str]]:
        """Return a snapshot of active multi-worker processes."""
        return dict(self._multi_workers)

    def _check_multi_worker_exclusive(self) -> None:
        """Raise if single-worker is active or if multi-workers are already running."""
        if self._active_backend is not None:
            raise MultiWorkerError(
                f"GPU lease busy with backend={self._active_backend}; "
                "cannot spawn multi-workers while single-worker is active"
            )
        if self._multi_workers:
            raise MultiWorkerError(
                f"{len(self._multi_workers)} multi-worker(s) already running; "
                "cannot spawn additional workers"
            )

    def spawn_multi_workers(
        self,
        worker_specs: dict[int, Sequence[str]],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> dict[int, int]:
        """Spawn N independent TTS worker subprocesses.

        Parameters
        ----------
        worker_specs : dict[int, Sequence[str]]
            Mapping of ``worker_id → command`` for each worker to spawn.
        cwd : Path | None
            Working directory for spawned processes.
        env : Mapping[str, str] | None
            Environment variables.  When *None* a scrubbed worker env is
            generated automatically.
        timeout_s : float | None
            Per-worker timeout (falls back to ``default_timeout_s``).

        Returns
        -------
        dict[int, int]
            Mapping of ``worker_id → pid`` for each spawned process.
        """
        self._check_multi_worker_exclusive()

        worker_count = len(worker_specs)
        if worker_count < 2:
            raise ValueError("spawn_multi_workers requires at least 2 workers")

        # VRAM check: N × (2800 + 200) MiB
        per_worker_mib = config.TTS_PER_WORKER_VRAM_MIB + config.TTS_PER_WORKER_OVERHEAD_MIB
        required_mib = worker_count * per_worker_mib
        self.guardian.require_safe_headroom(kind="load", backend="tts")
        self.guardian.log_event(
            "multi_spawn",
            backend="tts",
            worker_count=worker_count,
            required_mib=required_mib,
        )

        spawn_env = dict(env) if env is not None else None
        if spawn_env is None:
            spawn_env = merge_pytorch_alloc_conf()

        pids: dict[int, int] = {}
        procs: dict[int, subprocess.Popen[str]] = {}

        for worker_id, command in worker_specs.items():
            proc = subprocess.Popen(
                list(command),
                cwd=str(cwd) if cwd is not None else None,
                env=spawn_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            procs[worker_id] = proc
            pids[worker_id] = proc.pid  # type: ignore[assignment]
            self._multi_workers[worker_id] = proc
            logger.info(
                "[gpu] event=multi_spawn worker=%d pid=%d cmd=%s",
                worker_id,
                proc.pid,
                " ".join(command[:4]),
            )

        self._notify(None, "gpu-multi-worker", f"spawned {worker_count} workers")
        return pids

    def join_multi_workers(
        self,
        worker_ids: Sequence[int] | None = None,
        *,
        timeout_s: float | None = None,
    ) -> dict[int, WorkerResult]:
        """Wait for multi-workers to finish and collect results.

        Parameters
        ----------
        worker_ids : Sequence[int] | None
            Subset of worker ids to wait for.  *None* waits for all active
            multi-workers.
        timeout_s : float | None
            Per-worker timeout (falls back to ``default_timeout_s``).

        Returns
        -------
        dict[int, WorkerResult]
            Mapping of ``worker_id → WorkerResult`` for each waited worker.
        """
        timeout = self.default_timeout_s if timeout_s is None else timeout_s
        if worker_ids is not None:
            to_wait = list(worker_ids)
        else:
            to_wait = list(self._multi_workers.keys())

        if not to_wait:
            return {}

        results: dict[int, WorkerResult] = {}
        for worker_id in to_wait:
            proc = self._multi_workers.pop(worker_id, None)
            if proc is None:
                results[worker_id] = WorkerResult(
                    backend="tts",
                    exit_code=int(WorkerExitCode.SUCCESS),
                    returncode=int(WorkerExitCode.SUCCESS),
                    stdout="",
                    stderr="",
                )
                continue

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                returncode = proc.returncode if proc.returncode is not None else -1
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=30)
                returncode = proc.returncode if proc.returncode is not None else -1
                logger.warning(
                    "[gpu] event=multi_worker_timeout worker=%d timeout=%.0fs",
                    worker_id,
                    timeout,
                )

            results[worker_id] = WorkerResult(
                backend="tts",
                exit_code=returncode,
                returncode=returncode,
                stdout=stdout or "",
                stderr=stderr or "",
                timed_out=returncode == -1,
            )
            self.guardian.log_event("multi_worker_exit", backend="tts", worker_id=worker_id)

        # Surface [gpu] telemetry from worker logs.
        for worker_id, result in results.items():
            for stream_name, text in (("stdout", result.stdout), ("stderr", result.stderr)):
                if not text:
                    continue
                for line in text.splitlines():
                    if "[gpu]" in line:
                        logger.info("worker_%s w%d %s", stream_name, worker_id, line.strip())

        # Check if any worker failed fatally
        fatal = any(
            r.exit_code == int(WorkerExitCode.FATAL)
            for r in results.values()
        )
        if fatal:
            self._notify(None, "gpu-multi-worker", "fatal worker exit")

        self._notify(None, "gpu-multi-worker", f"join complete {len(results)} workers")
        return results

    def wait_multi_workers_free(self) -> None:
        """Release all active multi-workers and clear state."""
        if not self._multi_workers:
            return
        for worker_id, proc in list(self._multi_workers.items()):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            self.guardian.log_event("multi_worker_release", backend="tts", worker_id=worker_id)
        self._multi_workers.clear()
        self._notify(None, "gpu-multi-worker", "all workers released")

    @staticmethod
    def _notify(
        callback: ProgressCallback | None,
        stage: str,
        detail: str,
    ) -> None:
        if callback is not None:
            callback(stage, detail)
