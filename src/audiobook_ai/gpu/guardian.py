"""VRAMGuardian: thresholds, gates, progressive growth, error classification."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from audiobook_ai import config
from audiobook_ai.gpu.memory import MemoryProvider, SystemMemoryProvider, VRAMSnapshot
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)


class MemoryFailureKind(str, Enum):
    """Distinct VRAM policy failure classes (OOM is not normal control flow)."""

    MODEL_DOES_NOT_FIT = "model_does_not_fit"
    RUNTIME_HEADROOM_INSUFFICIENT = "runtime_headroom_insufficient"
    RELEASE_NOT_VERIFIED = "release_not_verified"
    PROGRESSIVE_GROWTH = "progressive_growth"
    BELOW_HARD_FLOOR = "below_hard_floor"
    UNEXPECTED_OOM = "unexpected_oom"


class MemoryPolicyError(RuntimeError):
    """Raised when a VRAM safety gate refuses work."""

    def __init__(
        self,
        message: str,
        *,
        kind: MemoryFailureKind,
        snapshot: VRAMSnapshot | None = None,
        backend: str | None = None,
        threshold_mib: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.snapshot = snapshot
        self.backend = backend
        self.threshold_mib = threshold_mib


@dataclass(frozen=True, slots=True)
class GuardianConfig:
    hard_floor_mib: int = config.HARD_FLOOR_MIB
    before_chunk_target_mib: int = config.BEFORE_CHUNK_TARGET_MIB
    load_targets_mib: dict[str, int] | None = None
    progressive_window_k: int = config.PROGRESSIVE_GROWTH_WINDOW_K
    progressive_drop_mib: int = config.PROGRESSIVE_GROWTH_DROP_MIB
    progressive_allocated_growth_mib: int = config.PROGRESSIVE_ALLOCATED_GROWTH_MIB
    progressive_floor_margin_mib: int = config.PROGRESSIVE_FLOOR_MARGIN_MIB

    def load_target_for(self, backend: str) -> int | None:
        targets = self.load_targets_mib
        if targets is None:
            targets = dict(config.BACKEND_LOAD_TARGET_MIB)
        return targets.get(backend)


@dataclass(frozen=True, slots=True)
class GrowthSample:
    """Post-reclaim VRAM sample for real-pressure progressive detection."""

    free_mib: float
    allocated_mib: float | None = None
    reserved_mib: float | None = None


class ProgressiveGrowthDetector:
    """Sliding-window detector for *real* VRAM pressure after reclaim.

    Free-drop alone with stable allocated/reserved and large free headroom
    MUST NOT trigger restart (Fish-era false positives on Qwen3-TTS).

    Restart when:
    - free_mib approaches hard_floor within ``floor_margin_mib``, OR
    - allocated_mib and/or reserved_mib grow persistently by ≥ ``growth_mib``
      over a full window with a consistent ascending trend.
    """

    def __init__(
        self,
        *,
        window_k: int,
        growth_mib: float,
        hard_floor_mib: float,
        floor_margin_mib: float,
    ) -> None:
        if window_k < 2:
            raise ValueError("progressive growth window_k must be >= 2")
        self.window_k = window_k
        self.growth_mib = growth_mib
        self.hard_floor_mib = hard_floor_mib
        self.floor_margin_mib = floor_margin_mib
        self._samples: deque[GrowthSample] = deque(maxlen=window_k)

    def reset(self) -> None:
        self._samples.clear()

    def record(self, sample: GrowthSample | float) -> bool:
        """Record a post-reclaim sample. Return True if real pressure detected.

        A bare ``float`` is treated as ``free_mib`` only (allocated/reserved
        unknown) — near-floor still triggers; free-drop alone does not.
        """
        if isinstance(sample, (int, float)):
            sample = GrowthSample(free_mib=float(sample))

        near_floor = sample.free_mib <= (self.hard_floor_mib + self.floor_margin_mib)
        if near_floor:
            return True

        self._samples.append(sample)
        if len(self._samples) < self.window_k:
            return False

        samples = list(self._samples)
        if self._persistent_growth(
            [s.allocated_mib for s in samples],
        ) or self._persistent_growth(
            [s.reserved_mib for s in samples],
        ):
            return True
        return False

    def _persistent_growth(self, values: list[float | None]) -> bool:
        if any(v is None for v in values):
            return False
        nums = [float(v) for v in values if v is not None]
        if len(nums) < self.window_k:
            return False
        cumulative = nums[-1] - nums[0]
        if cumulative < self.growth_mib:
            return False
        ascending = all(nums[i] <= nums[i + 1] + 1e-6 for i in range(len(nums) - 1))
        return ascending


class VRAMGuardian:
    """Decide whether GPU work is safe given system-reported free VRAM."""

    def __init__(
        self,
        provider: MemoryProvider | None = None,
        *,
        cfg: GuardianConfig | None = None,
    ) -> None:
        self.provider = provider or SystemMemoryProvider()
        self.cfg = cfg or GuardianConfig()
        self.growth = ProgressiveGrowthDetector(
            window_k=self.cfg.progressive_window_k,
            growth_mib=float(self.cfg.progressive_allocated_growth_mib),
            hard_floor_mib=float(self.cfg.hard_floor_mib),
            floor_margin_mib=float(self.cfg.progressive_floor_margin_mib),
        )

    def snapshot(self) -> VRAMSnapshot:
        return self.provider.snapshot()

    def wait_until_free(
        self,
        target_mib: float,
        *,
        timeout_s: float | None = None,
        poll_s: float | None = None,
        backend: str | None = None,
        event: str = "wait_free",
    ) -> VRAMSnapshot:
        """Poll system free VRAM until ``target_mib`` or timeout.

        ROCm / Ollama reclaim is often asynchronous after process exit or
        ``keep_alive=0``; a single snapshot right after unload is unreliable.
        """
        timeout = (
            config.VRAM_RELEASE_WAIT_TIMEOUT_S if timeout_s is None else timeout_s
        )
        poll = config.VRAM_RELEASE_POLL_S if poll_s is None else poll_s
        deadline = time.monotonic() + timeout
        snap = self.snapshot()
        self.log_event(event, backend=backend, snap=snap)
        while True:
            if snap.free_mib is not None and snap.free_mib >= target_mib:
                return snap
            if time.monotonic() >= deadline:
                raise MemoryPolicyError(
                    (
                        f"VRAM wait timed out after {timeout:.1f}s: "
                        f"free_mib={snap.free_mib} target_mib={target_mib}"
                    ),
                    kind=MemoryFailureKind.RELEASE_NOT_VERIFIED,
                    snapshot=snap,
                    backend=backend,
                    threshold_mib=target_mib,
                )
            time.sleep(poll)
            snap = self.snapshot()

    def can_start_chunk(self, snap: VRAMSnapshot | None = None) -> tuple[bool, str | None]:
        """Return (ok, reason). Below floor or below chunk target → not ok."""
        snap = snap or self.snapshot()
        if snap.free_mib is None:
            return False, "system free VRAM unavailable"
        if snap.free_mib < self.cfg.hard_floor_mib:
            return False, (
                f"free_mib={snap.free_mib:.1f} below hard_floor_mib="
                f"{self.cfg.hard_floor_mib}"
            )
        if snap.free_mib < self.cfg.before_chunk_target_mib:
            return False, (
                f"free_mib={snap.free_mib:.1f} below before_chunk_target_mib="
                f"{self.cfg.before_chunk_target_mib}"
            )
        return True, None

    def can_load_backend(
        self,
        backend: str,
        snap: VRAMSnapshot | None = None,
    ) -> tuple[bool, str | None]:
        """Return (ok, reason) for spawning/loading ``backend``."""
        snap = snap or self.snapshot()
        target = self.cfg.load_target_for(backend)
        if target is None:
            return False, (
                f"no before_load_target_mib configured for backend={backend!r}; "
                "unknown backends must not inherit Fish Speech defaults"
            )
        if snap.free_mib is None:
            return False, "system free VRAM unavailable"
        if snap.free_mib < self.cfg.hard_floor_mib:
            return False, (
                f"free_mib={snap.free_mib:.1f} below hard_floor_mib="
                f"{self.cfg.hard_floor_mib}"
            )
        if snap.free_mib < target:
            return False, (
                f"free_mib={snap.free_mib:.1f} below before_load_target_mib="
                f"{target} for backend={backend}"
            )
        return True, None

    def require_safe_headroom(
        self,
        *,
        kind: Literal["chunk", "load", "release"],
        backend: str | None = None,
        snap: VRAMSnapshot | None = None,
        release_target_mib: float | None = None,
    ) -> VRAMSnapshot:
        """Raise ``MemoryPolicyError`` with classified kind when unsafe."""
        snap = snap or self.snapshot()
        if kind == "chunk":
            ok, reason = self.can_start_chunk(snap)
            if not ok:
                failure = (
                    MemoryFailureKind.BELOW_HARD_FLOOR
                    if snap.free_mib is not None
                    and snap.free_mib < self.cfg.hard_floor_mib
                    else MemoryFailureKind.RUNTIME_HEADROOM_INSUFFICIENT
                )
                raise MemoryPolicyError(
                    f"unsafe to start SpeechChunk: {reason}",
                    kind=failure,
                    snapshot=snap,
                    backend=backend,
                    threshold_mib=float(
                        self.cfg.hard_floor_mib
                        if failure is MemoryFailureKind.BELOW_HARD_FLOOR
                        else self.cfg.before_chunk_target_mib
                    ),
                )
            return snap

        if kind == "load":
            if backend is None:
                raise ValueError("backend is required for load headroom checks")
            ok, reason = self.can_load_backend(backend, snap)
            if not ok:
                failure = (
                    MemoryFailureKind.BELOW_HARD_FLOOR
                    if snap.free_mib is not None
                    and snap.free_mib < self.cfg.hard_floor_mib
                    else MemoryFailureKind.MODEL_DOES_NOT_FIT
                )
                target = self.cfg.load_target_for(backend)
                raise MemoryPolicyError(
                    f"unsafe to load backend={backend}: {reason}",
                    kind=failure,
                    snapshot=snap,
                    backend=backend,
                    threshold_mib=float(target) if target is not None else None,
                )
            return snap

        # release verification
        target = release_target_mib
        if target is None and backend is not None:
            loaded = self.cfg.load_target_for(backend)
            target = float(loaded) if loaded is not None else float(self.cfg.hard_floor_mib)
        if target is None:
            target = float(self.cfg.hard_floor_mib)
        if snap.free_mib is None or snap.free_mib < target:
            raise MemoryPolicyError(
                (
                    f"VRAM release not verified after worker exit: "
                    f"free_mib={snap.free_mib} target_mib={target}"
                ),
                kind=MemoryFailureKind.RELEASE_NOT_VERIFIED,
                snapshot=snap,
                backend=backend,
                threshold_mib=target,
            )
        return snap

    def record_post_reclaim(
        self,
        free_or_snap: float | VRAMSnapshot | GrowthSample,
    ) -> bool:
        """Record post-reclaim metrics; True if real progressive pressure.

        Accepts free_mib float (legacy), ``GrowthSample``, or full snapshot.
        """
        if isinstance(free_or_snap, VRAMSnapshot):
            if free_or_snap.free_mib is None:
                return False
            sample = GrowthSample(
                free_mib=float(free_or_snap.free_mib),
                allocated_mib=free_or_snap.allocated_mib,
                reserved_mib=free_or_snap.reserved_mib,
            )
        elif isinstance(free_or_snap, GrowthSample):
            sample = free_or_snap
        else:
            sample = GrowthSample(free_mib=float(free_or_snap))

        detected = self.growth.record(sample)
        if detected:
            logger.info(
                "[gpu] event=progressive_growth free_mib=%.1f allocated_mib=%s "
                "reserved_mib=%s window_k=%s growth_mib=%s floor_margin_mib=%s",
                sample.free_mib,
                None
                if sample.allocated_mib is None
                else f"{sample.allocated_mib:.1f}",
                None
                if sample.reserved_mib is None
                else f"{sample.reserved_mib:.1f}",
                self.cfg.progressive_window_k,
                self.cfg.progressive_allocated_growth_mib,
                self.cfg.progressive_floor_margin_mib,
            )
        return detected

    def reset_growth_window(self) -> None:
        self.growth.reset()

    def log_event(
        self,
        event: str,
        *,
        backend: str | None = None,
        chunk_id: str | None = None,
        snap: VRAMSnapshot | None = None,
        **extra: Any,
    ) -> None:
        snap = snap or self.snapshot()
        fm = f"{snap.free_mib:.1f}" if snap.free_mib is not None else None
        am = f"{snap.allocated_mib:.1f}" if snap.allocated_mib is not None else None
        rm = f"{snap.reserved_mib:.1f}" if snap.reserved_mib is not None else None
        parts: list[str] = [
            f"[gpu] backend={backend}",
            f"event={event}",
            f"chunk_id={chunk_id}",
            f"free_mib={fm}",
            f"allocated_mib={am}",
            f"reserved_mib={rm}",
        ]
        for k, v in extra.items():
            parts.append(f"{k}={v}")
        logger.info(" ".join(parts))
