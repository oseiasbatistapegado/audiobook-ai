"""Unit tests for VRAMGuardian with a fake memory provider."""

from __future__ import annotations

import pytest

from audiobook_ai.gpu.guardian import (
    GuardianConfig,
    MemoryFailureKind,
    MemoryPolicyError,
    ProgressiveGrowthDetector,
    VRAMGuardian,
)
from audiobook_ai.gpu.memory import VRAMSnapshot


class FakeMemoryProvider:
    def __init__(self, free_mib: float, *, total_mib: float = 24576.0) -> None:
        self.free_mib = free_mib
        self.total_mib = total_mib
        self.allocated_mib: float | None = 100.0
        self.reserved_mib: float | None = 200.0

    def snapshot(self) -> VRAMSnapshot:
        return VRAMSnapshot(
            total_mib=self.total_mib,
            free_mib=self.free_mib,
            allocated_mib=self.allocated_mib,
            reserved_mib=self.reserved_mib,
        )


def _guardian(free_mib: float, **cfg_overrides: object) -> VRAMGuardian:
    cfg = GuardianConfig(**cfg_overrides) if cfg_overrides else GuardianConfig()
    return VRAMGuardian(FakeMemoryProvider(free_mib), cfg=cfg)


def test_refuse_below_hard_floor() -> None:
    g = _guardian(200.0)
    ok, reason = g.can_start_chunk()
    assert ok is False
    assert reason is not None and "hard_floor" in reason
    with pytest.raises(MemoryPolicyError) as exc:
        g.require_safe_headroom(kind="chunk")
    assert exc.value.kind is MemoryFailureKind.BELOW_HARD_FLOOR


def test_refuse_chunk_below_target_above_floor() -> None:
    g = _guardian(500.0)  # above 300 floor, below 768 target
    ok, reason = g.can_start_chunk()
    assert ok is False
    assert reason is not None and "before_chunk_target" in reason
    with pytest.raises(MemoryPolicyError) as exc:
        g.require_safe_headroom(kind="chunk")
    assert exc.value.kind is MemoryFailureKind.RUNTIME_HEADROOM_INSUFFICIENT


def test_chunk_ok_above_target() -> None:
    g = _guardian(900.0)
    ok, reason = g.can_start_chunk()
    assert ok is True
    assert reason is None


def test_fish_load_target_separate_from_parler() -> None:
    g = _guardian(5000.0)  # below s1-mini load 8192, above parler 8192? parler is also 8192
    # Use free between parler... wait both are 8192 now.
    # Fish product default 8192; parler 8192 — separate via explicit cfg.
    g = VRAMGuardian(
        FakeMemoryProvider(5000.0),
        cfg=GuardianConfig(
            load_targets_mib={"fish-speech": 8192, "parler": 4096},
        ),
    )
    ok_fish, reason_fish = g.can_load_backend("fish-speech")
    assert ok_fish is False
    assert reason_fish is not None and "8192" in reason_fish

    ok_parler, reason_parler = g.can_load_backend("parler")
    assert ok_parler is True
    assert reason_parler is None

    with pytest.raises(MemoryPolicyError) as exc:
        g.require_safe_headroom(kind="load", backend="fish-speech")
    assert exc.value.kind is MemoryFailureKind.MODEL_DOES_NOT_FIT


def test_unknown_backend_does_not_inherit_fish() -> None:
    g = _guardian(24000.0)
    ok, reason = g.can_load_backend("mystery-tts")
    assert ok is False
    assert reason is not None
    assert "must not inherit" in reason
    assert "8192" not in reason
    assert "22528" not in reason


def test_progressive_growth_sustained_trend() -> None:
    detector = ProgressiveGrowthDetector(window_k=3, drop_mib=256)
    assert detector.record(2000.0) is False
    assert detector.record(1800.0) is False
    # Drop 400 over window, monotonic descent → detect
    assert detector.record(1600.0) is True


def test_progressive_growth_isolated_sample_no_false_positive() -> None:
    detector = ProgressiveGrowthDetector(window_k=3, drop_mib=256)
    assert detector.record(2000.0) is False
    # Single sharp drop, then recovery — window not consistently descending
    assert detector.record(1500.0) is False
    assert detector.record(1950.0) is False


def test_release_not_verified_distinct_message() -> None:
    g = _guardian(500.0)
    with pytest.raises(MemoryPolicyError) as exc:
        g.require_safe_headroom(
            kind="release",
            backend="parler",
            release_target_mib=8192.0,
        )
    assert exc.value.kind is MemoryFailureKind.RELEASE_NOT_VERIFIED
    assert "release not verified" in str(exc.value).lower()


def test_error_kinds_have_distinct_messages() -> None:
    messages: dict[MemoryFailureKind, str] = {}

    g_floor = _guardian(100.0)
    with pytest.raises(MemoryPolicyError) as e1:
        g_floor.require_safe_headroom(kind="chunk")
    messages[e1.value.kind] = str(e1.value)

    g_chunk = _guardian(500.0)
    with pytest.raises(MemoryPolicyError) as e2:
        g_chunk.require_safe_headroom(kind="chunk")
    messages[e2.value.kind] = str(e2.value)

    g_load = _guardian(5000.0)
    with pytest.raises(MemoryPolicyError) as e3:
        g_load.require_safe_headroom(kind="load", backend="fish-speech")
    messages[e3.value.kind] = str(e3.value)

    g_rel = _guardian(100.0)
    with pytest.raises(MemoryPolicyError) as e4:
        g_rel.require_safe_headroom(kind="release", release_target_mib=1000.0)
    messages[e4.value.kind] = str(e4.value)

    assert len(messages) == 4
    assert len(set(messages.values())) == 4


def test_wait_until_free_polls_until_target() -> None:
    provider = FakeMemoryProvider(100.0)
    g = VRAMGuardian(provider, cfg=GuardianConfig())
    steps = {"n": 0}
    original = provider.snapshot

    def flaky_snapshot() -> VRAMSnapshot:
        steps["n"] += 1
        if steps["n"] >= 3:
            provider.free_mib = 900.0
        return original()

    provider.snapshot = flaky_snapshot  # type: ignore[method-assign]
    snap = g.wait_until_free(800.0, timeout_s=2.0, poll_s=0.01)
    assert snap.free_mib is not None and snap.free_mib >= 800.0
    assert steps["n"] >= 3


def test_wait_until_free_times_out() -> None:
    g = _guardian(100.0)
    with pytest.raises(MemoryPolicyError) as exc:
        g.wait_until_free(800.0, timeout_s=0.05, poll_s=0.01)
    assert exc.value.kind is MemoryFailureKind.RELEASE_NOT_VERIFIED
