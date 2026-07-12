"""VRAMGuardian: thresholds, gates, progressive growth, error classification."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Literal

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

    def load_target_for(self, backend: str) -> int | None:
        targets = self.load_targets_mib
        if targets is None:
            targets = dict(config.BACKEND_LOAD_TARGET_MIB)
        return targets.get(backend)


class ProgressiveGrowthDetector:
    """Sliding-window detector for sustained free-VRAM decline after reclaim.

    A single anomalous sample MUST NOT trigger restart. Requires window size
    ``K`` and cumulative drop ≥ ``N`` MiB with a consistently descending trend.
    """

    def __init__(self, *, window_k: int, drop_mib: float) -> None:
        if window_k < 2:
            raise ValueError("progressive growth window_k must be >= 2")
        self.window_k = window_k
        self.drop_mib = drop_mib
        self._samples: deque[float] = deque(maxlen=window_k)

    def reset(self) -> None:
        self._samples.clear()

    def record(self, free_mib: float) -> bool:
        """Record a post-reclaim free sample. Return True if growth detected."""
        self._samples.append(free_mib)
        if len(self._samples) < self.window_k:
            return False
        samples = list(self._samples)
        cumulative_drop = samples[0] - samples[-1]
        if cumulative_drop < self.drop_mib:
            return False
        # Consistent descent: each step decreases (allow tiny epsilon noise).
        descending = all(
            samples[i] >= samples[i + 1] - 1e-6 for i in range(len(samples) - 1)
        )
        return descending


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
            drop_mib=float(self.cfg.progressive_drop_mib),
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

    def record_post_reclaim(self, free_mib: float) -> bool:
        """Record post-reclaim free; True if progressive growth demands restart."""
        detected = self.growth.record(free_mib)
        if detected:
            logger.info(
                "[gpu] event=progressive_growth free_mib=%.1f window_k=%s drop_mib=%s",
                free_mib,
                self.cfg.progressive_window_k,
                self.cfg.progressive_drop_mib,
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
    ) -> None:
        snap = snap or self.snapshot()
        logger.info(
            "[gpu] backend=%s event=%s chunk_id=%s free_mib=%s allocated_mib=%s "
            "reserved_mib=%s",
            backend,
            event,
            chunk_id,
            None if snap.free_mib is None else f"{snap.free_mib:.1f}",
            None if snap.allocated_mib is None else f"{snap.allocated_mib:.1f}",
            None if snap.reserved_mib is None else f"{snap.reserved_mib:.1f}",
        )
