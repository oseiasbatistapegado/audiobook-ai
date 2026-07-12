"""VRAM snapshots and pluggable memory providers."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol

from audiobook_ai import config
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class VRAMSnapshot:
    """Point-in-time VRAM metrics.

    ``free_mib`` is system-reported free VRAM and is authoritative for desktop
    safety. ``allocated_mib`` / ``reserved_mib`` are PyTorch telemetry when
    available and MUST NOT be treated as interchangeable with free.
    """

    total_mib: float | None
    free_mib: float | None
    allocated_mib: float | None = None
    reserved_mib: float | None = None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "total_mib": self.total_mib,
            "free_mib": self.free_mib,
            "allocated_mib": self.allocated_mib,
            "reserved_mib": self.reserved_mib,
        }


class MemoryProvider(Protocol):
    """Pluggable source of VRAM metrics (real GPU or fake for tests)."""

    def snapshot(self) -> VRAMSnapshot: ...


class SystemMemoryProvider:
    """Read system free VRAM plus optional PyTorch alloc/reserved."""

    def snapshot(self) -> VRAMSnapshot:
        total_mib, free_mib = _system_vram_mib()
        allocated_mib, reserved_mib = _torch_vram_mib()
        return VRAMSnapshot(
            total_mib=total_mib,
            free_mib=free_mib,
            allocated_mib=allocated_mib,
            reserved_mib=reserved_mib,
        )


def apply_process_vram_reserve(
    reserve_mib: int | None = None,
    *,
    total_mib: float | None = None,
) -> float | None:
    """Cap this process's CUDA/HIP allocator so the compositor keeps headroom.

    Empirical RX 7900 XTX (2026-07-12): Fish synth peaks drove system free to
    ~160 MiB and amdgpu returned "Not enough memory for command submission",
    crashing Hyprland/Cursor. ``hard_floor`` gates alone cannot stop mid-synth
    peaks; a per-process allocator cap forces Fish to OOM instead of the desktop.
    """
    reserve = float(reserve_mib if reserve_mib is not None else config.GPU_PROCESS_RESERVE_MIB)
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        if total_mib is None or total_mib <= 0:
            _total, _free = _system_vram_mib()
            if _total is None or _total <= 0:
                _free_b, total_b = torch.cuda.mem_get_info()
                total_mib = total_b / (1024 * 1024)
            else:
                total_mib = float(_total)
        usable = max(total_mib - reserve, 1.0)
        fraction = min(max(usable / total_mib, 0.05), 0.99)
        torch.cuda.set_per_process_memory_fraction(fraction)
        logger.info(
            "[gpu] event=process_vram_cap reserve_mib=%.0f total_mib=%.0f fraction=%.4f",
            reserve,
            total_mib,
            fraction,
        )
        return fraction
    except Exception:  # noqa: BLE001
        logger.debug("process VRAM reserve failed", exc_info=True)
        return None


def is_cuda_oom(exc: BaseException) -> bool:
    """Detect allocator / HIP / CUDA out-of-memory failures."""
    text = f"{type(exc).__name__}: {exc}".lower()
    needles = (
        "out of memory",
        "oom",
        "hiperroroutofmemory",
        "cuda error: out of memory",
        "cnmem",
        "not enough memory",
    )
    return any(n in text for n in needles)


def _system_vram_mib() -> tuple[float | None, float | None]:
    """System free/total: prefer rocm-smi (desktop-authoritative), then torch."""
    rocm = _rocm_smi_vram_mib()
    if rocm != (None, None):
        return rocm

    try:
        import torch

        if torch.cuda.is_available():
            free_b, total_b = torch.cuda.mem_get_info()
            return total_b / (1024 * 1024), free_b / (1024 * 1024)
    except Exception:  # noqa: BLE001 — telemetry must never crash callers
        logger.debug("system VRAM probe via torch.cuda.mem_get_info failed", exc_info=True)
    return None, None


def _rocm_smi_vram_mib() -> tuple[float | None, float | None]:
    """Parse rocm-smi VRAM total/used → (total_mib, free_mib)."""
    if shutil.which("rocm-smi") is None:
        return None, None
    try:
        completed = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if completed.returncode != 0:
            return None, None
        text = completed.stdout
        total_m = re.search(r"Total Memory \(B\):\s*([0-9]+)", text)
        used_m = re.search(r"Total Used Memory \(B\):\s*([0-9]+)", text)
        if total_m and used_m:
            total = float(total_m.group(1)) / (1024 * 1024)
            used = float(used_m.group(1)) / (1024 * 1024)
            return total, max(0.0, total - used)
    except Exception:  # noqa: BLE001
        logger.debug("system VRAM probe via rocm-smi failed", exc_info=True)
    return None, None


def _torch_vram_mib() -> tuple[float | None, float | None]:
    try:
        import torch

        if not torch.cuda.is_available():
            return None, None
        allocated = torch.cuda.memory_allocated() / (1024 * 1024)
        reserved = torch.cuda.memory_reserved() / (1024 * 1024)
        return allocated, reserved
    except Exception:  # noqa: BLE001
        return None, None
