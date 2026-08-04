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


def test_tts_load_target_separate_from_parler() -> None:
    g = _guardian(5000.0)  # below tts load 8192, above parler 4096
    g = VRAMGuardian(
        FakeMemoryProvider(5000.0),
        cfg=GuardianConfig(
            load_targets_mib={"tts": 8192, "qwen3-tts": 8192, "parler": 4096},
        ),
    )
    ok_tts, reason_tts = g.can_load_backend("tts")
    assert ok_tts is False
    assert reason_tts is not None and "8192" in reason_tts

    ok_parler, reason_parler = g.can_load_backend("parler")
    assert ok_parler is True
    assert reason_parler is None

    with pytest.raises(MemoryPolicyError) as exc:
        g.require_safe_headroom(kind="load", backend="tts")
    assert exc.value.kind is MemoryFailureKind.MODEL_DOES_NOT_FIT


def test_unknown_backend_does_not_inherit_tts() -> None:
    g = _guardian(24000.0)
    ok, reason = g.can_load_backend("mystery-tts")
    assert ok is False
    assert reason is not None
    assert "must not inherit" in reason
    assert "8192" not in reason
    assert "22528" not in reason


def test_progressive_growth_allocated_trend() -> None:
    detector = ProgressiveGrowthDetector(
        window_k=3,
        growth_mib=256,
        hard_floor_mib=300,
        floor_margin_mib=512,
    )
    from audiobook_ai.gpu.guardian import GrowthSample

    assert (
        detector.record(
            GrowthSample(free_mib=20000.0, allocated_mib=2000.0, reserved_mib=2100.0)
        )
        is False
    )
    assert (
        detector.record(
            GrowthSample(free_mib=19800.0, allocated_mib=2200.0, reserved_mib=2300.0)
        )
        is False
    )
    # Allocated grew ≥256 with ascending trend → real pressure
    assert (
        detector.record(
            GrowthSample(free_mib=19600.0, allocated_mib=2400.0, reserved_mib=2500.0)
        )
        is True
    )


def test_progressive_growth_free_drop_stable_alloc_no_false_positive() -> None:
    """Fish-era free-drop must not restart when allocated is stable and free is high."""
    detector = ProgressiveGrowthDetector(
        window_k=3,
        growth_mib=256,
        hard_floor_mib=300,
        floor_margin_mib=512,
    )
    from audiobook_ai.gpu.guardian import GrowthSample

    assert (
        detector.record(
            GrowthSample(free_mib=21300.0, allocated_mib=2212.0, reserved_mib=2232.0)
        )
        is False
    )
    assert (
        detector.record(
            GrowthSample(free_mib=20900.0, allocated_mib=2212.0, reserved_mib=2232.0)
        )
        is False
    )
    assert (
        detector.record(
            GrowthSample(free_mib=20600.0, allocated_mib=2212.0, reserved_mib=2232.0)
        )
        is False
    )


def test_progressive_growth_near_hard_floor() -> None:
    detector = ProgressiveGrowthDetector(
        window_k=3,
        growth_mib=256,
        hard_floor_mib=300,
        floor_margin_mib=512,
    )
    from audiobook_ai.gpu.guardian import GrowthSample

    # free <= 300+512 → pressure even on first sample
    assert (
        detector.record(
            GrowthSample(free_mib=700.0, allocated_mib=2212.0, reserved_mib=2232.0)
        )
        is True
    )


def test_progressive_growth_isolated_sample_no_false_positive() -> None:
    detector = ProgressiveGrowthDetector(
        window_k=3,
        growth_mib=256,
        hard_floor_mib=300,
        floor_margin_mib=512,
    )
    from audiobook_ai.gpu.guardian import GrowthSample

    assert (
        detector.record(
            GrowthSample(free_mib=20000.0, allocated_mib=2000.0, reserved_mib=2100.0)
        )
        is False
    )
    assert (
        detector.record(
            GrowthSample(free_mib=19500.0, allocated_mib=2500.0, reserved_mib=2600.0)
        )
        is False
    )
    # Recovery — not consistently ascending allocated
    assert (
        detector.record(
            GrowthSample(free_mib=19900.0, allocated_mib=2100.0, reserved_mib=2200.0)
        )
        is False
    )


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

    g_load = _guardian(2000.0)
    with pytest.raises(MemoryPolicyError) as e3:
        g_load.require_safe_headroom(kind="load", backend="tts")
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
