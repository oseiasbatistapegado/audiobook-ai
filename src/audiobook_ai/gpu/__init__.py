"""GPU memory monitoring, VRAM guardian, and worker lifecycle."""

from __future__ import annotations

from audiobook_ai.gpu.guardian import (
    MemoryFailureKind,
    MemoryPolicyError,
    ProgressiveGrowthDetector,
    VRAMGuardian,
)
from audiobook_ai.gpu.lifecycle import (
    LifecycleError,
    LifecycleManager,
    WorkerLeaseBusyError,
    WorkerResult,
)
from audiobook_ai.gpu.memory import (
    MemoryProvider,
    SystemMemoryProvider,
    VRAMSnapshot,
    apply_process_vram_reserve,
    is_cuda_oom,
)

__all__ = [
    "LifecycleError",
    "LifecycleManager",
    "MemoryFailureKind",
    "MemoryPolicyError",
    "MemoryProvider",
    "ProgressiveGrowthDetector",
    "SystemMemoryProvider",
    "VRAMGuardian",
    "VRAMSnapshot",
    "WorkerLeaseBusyError",
    "WorkerResult",
    "apply_process_vram_reserve",
    "is_cuda_oom",
]
