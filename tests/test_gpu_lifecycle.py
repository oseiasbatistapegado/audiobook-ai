"""LifecycleManager tests with fake workers (no real GPU)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from audiobook_ai.gpu.guardian import GuardianConfig, VRAMGuardian
from audiobook_ai.gpu.jobs import WorkerExitCode
from audiobook_ai.gpu.lifecycle import (
    CompletedProcessLike,
    LifecycleError,
    LifecycleManager,
    WorkerLeaseBusyError,
)
from audiobook_ai.gpu.memory import VRAMSnapshot


class FakeProvider:
    def __init__(self, free_mib: float) -> None:
        self.free_mib = free_mib

    def snapshot(self) -> VRAMSnapshot:
        return VRAMSnapshot(total_mib=24576.0, free_mib=self.free_mib)


def _mgr(free_mib: float = 24000.0) -> tuple[LifecycleManager, FakeProvider]:
    provider = FakeProvider(free_mib)
    # Low load targets so fake workers can start in unit tests.
    cfg = GuardianConfig(
        load_targets_mib={"fish-speech": 1000, "parler": 500},
        hard_floor_mib=300,
        before_chunk_target_mib=768,
    )
    guardian = VRAMGuardian(provider, cfg=cfg)
    return LifecycleManager(guardian, spawn_fn=None), provider


def test_lease_blocks_second_active_worker() -> None:
    mgr, provider = _mgr()
    active = {"held": False}

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        active["held"] = True
        # While "running", attempt a nested spawn via the same manager.
        with pytest.raises(WorkerLeaseBusyError):
            mgr.run_worker(
                "fish-speech",
                ["false"],
                skip_load_gate=True,
                verify_release=False,
            )
        active["held"] = False
        provider.free_mib = 24000.0
        return CompletedProcessLike(returncode=0)

    mgr._spawn_fn = spawn
    result = mgr.run_worker(
        "parler",
        ["true"],
        skip_load_gate=True,
        verify_release=True,
        release_target_mib=1000.0,
    )
    assert result.success
    assert mgr.active_backend is None


def test_voice_design_then_verify_then_fish_order() -> None:
    mgr, provider = _mgr()
    events: list[str] = []

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cwd
        backend = "parler" if "parler" in " ".join(cmd) else "fish-speech"
        events.append(f"run:{backend}")
        provider.free_mib = 20000.0  # released after exit
        return CompletedProcessLike(returncode=0)

    mgr._spawn_fn = spawn

    def on_progress(stage: str, detail: str) -> None:
        events.append(f"{stage}:{detail}")

    mgr.run_worker(
        "parler",
        ["worker", "parler"],
        progress_callback=on_progress,
        next_backend_for_release="fish-speech",
        release_target_mib=1000.0,
    )
    events.append("verified-before-fish")
    mgr.run_worker(
        "fish-speech",
        ["worker", "fish-speech"],
        progress_callback=on_progress,
        release_target_mib=1000.0,
    )

    assert events[0].startswith("gpu-worker:spawn parler")
    assert "run:parler" in events
    assert "verified-before-fish" in events
    assert events.index("run:parler") < events.index("verified-before-fish")
    assert events.index("verified-before-fish") < events.index("run:fish-speech")


def test_controlled_restart_respects_budget() -> None:
    mgr, provider = _mgr()
    calls = {"n": 0}

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        calls["n"] += 1
        provider.free_mib = 20000.0
        return CompletedProcessLike(
            returncode=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
        )

    mgr._spawn_fn = spawn

    with pytest.raises(LifecycleError, match="restart budget exhausted"):
        mgr.run_fish_with_restarts(
            lambda: ["fish"],
            restart_budget=3,
            # High stall limit so optional global budget is what aborts.
            no_progress_limit=100,
            has_pending=lambda: True,
            skip_load_gate=True,
        )
    # initial + 3 charged restarts = 4 attempts
    assert calls["n"] == 4


def test_controlled_restart_succeeds_within_budget() -> None:
    mgr, provider = _mgr()
    calls = {"n": 0}

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        calls["n"] += 1
        provider.free_mib = 20000.0
        if calls["n"] < 3:
            return CompletedProcessLike(
                returncode=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
            )
        return CompletedProcessLike(returncode=int(WorkerExitCode.SUCCESS))

    mgr._spawn_fn = spawn
    result = mgr.run_fish_with_restarts(
        lambda: ["fish"],
        restart_budget=3,
        no_progress_limit=100,
        has_pending=lambda: True,
        skip_load_gate=True,
    )
    assert result.success
    assert calls["n"] == 3


def test_planned_restart_reasons_do_not_consume_budget() -> None:
    """progressive / headroom / residency restarts must not burn budget."""
    mgr, provider = _mgr()
    calls = {"n": 0}
    reasons = ["progressive", "headroom", "residency", "progressive", "headroom"]

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        calls["n"] += 1
        provider.free_mib = 20000.0
        if calls["n"] <= len(reasons):
            return CompletedProcessLike(
                returncode=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
            )
        return CompletedProcessLike(returncode=int(WorkerExitCode.SUCCESS))

    mgr._spawn_fn = spawn
    reason_idx = {"i": 0}

    def counts_against_budget(_result: object) -> bool:
        return False  # all planned in this test

    def restart_reason_fn(_result: object) -> str | None:
        i = reason_idx["i"]
        reason_idx["i"] = min(i + 1, len(reasons) - 1)
        return reasons[min(i, len(reasons) - 1)]

    result = mgr.run_fish_with_restarts(
        lambda: ["fish"],
        restart_budget=1,  # would exhaust immediately if charged
        no_progress_limit=1,  # would stall if charged
        has_pending=lambda: True,
        skip_load_gate=True,
        counts_against_budget=counts_against_budget,
        restart_reason_fn=restart_reason_fn,
    )
    assert result.success
    assert calls["n"] == len(reasons) + 1


def test_budget_disabled_does_not_abort_on_many_ooms_with_progress() -> None:
    """With budget=0, OOM+progress continues past what an old budget=8 would allow."""
    mgr, provider = _mgr()
    calls = {"n": 0}
    completed = {"n": 0}

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        calls["n"] += 1
        provider.free_mib = 20000.0
        # Each charged OOM worker "completes" one chunk before dying.
        completed["n"] += 1
        if calls["n"] < 12:
            return CompletedProcessLike(
                returncode=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
            )
        return CompletedProcessLike(returncode=int(WorkerExitCode.SUCCESS))

    mgr._spawn_fn = spawn
    chunk_ids = [f"ch-{i:06d}" for i in range(20)]

    result = mgr.run_fish_with_restarts(
        lambda: ["fish"],
        restart_budget=0,
        no_progress_limit=3,
        has_pending=lambda: True,
        skip_load_gate=True,
        counts_against_budget=lambda _r: True,
        restart_reason_fn=lambda _r: "oom",
        completed_count=lambda: completed["n"],
        # Distinct chunk each time so per-chunk gate does not fire.
        oom_chunk_id_fn=lambda _r: chunk_ids[min(calls["n"] - 1, len(chunk_ids) - 1)],
    )
    assert result.success
    assert calls["n"] == 12


def test_oom_stall_without_progress_aborts() -> None:
    mgr, provider = _mgr()
    calls = {"n": 0}

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        calls["n"] += 1
        provider.free_mib = 20000.0
        return CompletedProcessLike(
            returncode=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
        )

    mgr._spawn_fn = spawn

    with pytest.raises(LifecycleError, match="OOM stall"):
        mgr.run_fish_with_restarts(
            lambda: ["fish"],
            restart_budget=0,
            no_progress_limit=3,
            has_pending=lambda: True,
            skip_load_gate=True,
            counts_against_budget=lambda _r: True,
            restart_reason_fn=lambda _r: "oom",
            completed_count=lambda: 0,
            oom_chunk_id_fn=lambda _r: f"ch-{calls['n']:06d}",
        )
    # stall_limit charged restarts then abort (no further spawn)
    assert calls["n"] == 3


def test_oom_same_chunk_max_attempts_aborts() -> None:
    mgr, provider = _mgr()
    calls = {"n": 0}
    completed = {"n": 0}

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        calls["n"] += 1
        provider.free_mib = 20000.0
        # Fake progress so stall does not fire; same chunk id still aborts.
        completed["n"] += 1
        return CompletedProcessLike(
            returncode=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
        )

    mgr._spawn_fn = spawn

    with pytest.raises(LifecycleError, match="OOM limit for chunk ch-stuck"):
        mgr.run_fish_with_restarts(
            lambda: ["fish"],
            restart_budget=0,
            no_progress_limit=100,
            chunk_max_oom_attempts=3,
            has_pending=lambda: True,
            skip_load_gate=True,
            counts_against_budget=lambda _r: True,
            restart_reason_fn=lambda _r: "oom",
            completed_count=lambda: completed["n"],
            oom_chunk_id_fn=lambda _r: "ch-stuck",
        )
    assert calls["n"] == 3


def test_oom_restart_consumes_optional_budget() -> None:
    mgr, provider = _mgr()
    calls = {"n": 0}
    details: list[str] = []

    def spawn(cmd: Sequence[str], cwd: Path | None) -> CompletedProcessLike:
        del cmd, cwd
        calls["n"] += 1
        provider.free_mib = 20000.0
        return CompletedProcessLike(
            returncode=int(WorkerExitCode.CONTROLLED_RESTART_NEEDED)
        )

    mgr._spawn_fn = spawn

    def on_progress(stage: str, detail: str) -> None:
        if stage == "gpu-worker":
            details.append(detail)

    with pytest.raises(LifecycleError, match="restart budget exhausted"):
        mgr.run_fish_with_restarts(
            lambda: ["fish"],
            restart_budget=2,
            no_progress_limit=100,
            has_pending=lambda: True,
            skip_load_gate=True,
            counts_against_budget=lambda _r: True,
            restart_reason_fn=lambda _r: "oom",
            progress_callback=on_progress,
        )
    assert calls["n"] == 3  # initial + 2 charged restarts
    assert any("oom" in d for d in details)


def test_merge_pytorch_alloc_conf_default_and_override() -> None:
    from audiobook_ai.gpu.lifecycle import merge_pytorch_alloc_conf

    defaulted = merge_pytorch_alloc_conf({})
    assert defaulted["PYTORCH_HIP_ALLOC_CONF"] == "expandable_segments:True"
    assert defaulted["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True"

    overridden = merge_pytorch_alloc_conf(
        {
            "PYTORCH_HIP_ALLOC_CONF": "max_split_size_mb:128",
            "PYTORCH_CUDA_ALLOC_CONF": "garbage_collection_threshold:0.8",
        }
    )
    assert overridden["PYTORCH_HIP_ALLOC_CONF"] == "max_split_size_mb:128"
    assert overridden["PYTORCH_CUDA_ALLOC_CONF"] == "garbage_collection_threshold:0.8"


def test_per_chunk_attempt_tracking_helper() -> None:
    """Orchestrator policy: 2 attempts per chunk id — unit of the counter."""
    attempts: dict[str, int] = {}
    max_attempts = 2
    chunk_id = "ch-000001"

    def record_failure(cid: str) -> bool:
        attempts[cid] = attempts.get(cid, 0) + 1
        return attempts[cid] >= max_attempts

    assert record_failure(chunk_id) is False  # 1st failure — may retry
    assert record_failure(chunk_id) is True  # 2nd failure — abort
