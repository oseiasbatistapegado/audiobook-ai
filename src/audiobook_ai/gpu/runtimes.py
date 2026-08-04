"""Resolve per-phase worker Python interpreters (isolated dependency stacks).

Parler requires ``transformers==4.46.1``; ``qwen-tts`` requires
``transformers==4.57.3``. Those pins cannot share one site-packages tree.
Workers communicate only via filesystem artifacts (``reference.wav`` /
``reference.txt``), so each phase MAY use a distinct interpreter.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

ENV_VOICE_DESIGN_PYTHON = "AUDIOBOOK_AI_VOICE_DESIGN_PYTHON"
ENV_TTS_PYTHON = "AUDIOBOOK_AI_TTS_PYTHON"

# Repo-local default for the Parler-only venv (created by scripts/bootstrap_parler_venv.sh).
DEFAULT_VOICE_DESIGN_VENV = Path(".venv-parler")

# Host/Nix PYTHONPATH must not leak into isolated worker interpreters.
_SCRUB_ENV_KEYS = ("PYTHONPATH", "PYTHONHOME")


def worker_env(
    *,
    base: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a subprocess env for an isolated worker python.

    Scrubs host ``PYTHONPATH`` / ``PYTHONHOME`` so Nix/direnv paths do not
    shadow the worker venv's ``site-packages``.
    """
    env = dict(os.environ if base is None else base)
    for key in _SCRUB_ENV_KEYS:
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def resolve_tts_python() -> str:
    """Interpreter for the Qwen3-TTS worker (product default / current process)."""
    override = os.environ.get(ENV_TTS_PYTHON)
    if override and override.strip():
        return _require_executable(override.strip(), kind="tts")
    return sys.executable


def resolve_voice_design_python(
    *,
    project_root: Path | None = None,
) -> str:
    """Interpreter for the Parler Voice Design worker.

    Priority:
    1. ``AUDIOBOOK_AI_VOICE_DESIGN_PYTHON``
    2. ``<project>/.venv-parler/bin/python`` when present
    3. Current process interpreter (same-runtime fallback; may fail Parler load)
    """
    override = os.environ.get(ENV_VOICE_DESIGN_PYTHON)
    if override and override.strip():
        return _require_executable(override.strip(), kind="voice-design")

    root = project_root or _default_project_root()
    candidate = root / DEFAULT_VOICE_DESIGN_VENV / "bin" / "python"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        logger.info(
            "voice-design runtime=isolated python=%s",
            candidate,
        )
        # Keep the venv shim path (do not resolve symlinks — resolved base
        # python would skip .venv-parler site-packages).
        return str(candidate.absolute())

    logger.warning(
        "voice-design runtime=shared python=%s "
        "(create .venv-parler via scripts/bootstrap_parler_venv.sh "
        "or set %s — Parler needs transformers==4.46.1)",
        sys.executable,
        ENV_VOICE_DESIGN_PYTHON,
    )
    return sys.executable


def _default_project_root() -> Path:
    # src/audiobook_ai/gpu/runtimes.py → parents: gpu, audiobook_ai, src, repo
    return Path(__file__).resolve().parents[3]


def _require_executable(path: str, *, kind: str) -> str:
    resolved = Path(path).expanduser()
    if resolved.is_file() and os.access(resolved, os.X_OK):
        return str(resolved.absolute())
    which = shutil.which(path)
    if which:
        return which
    raise FileNotFoundError(
        f"Worker python for {kind} not found: {path!r}. "
        f"Set {ENV_VOICE_DESIGN_PYTHON if kind == 'voice-design' else ENV_TTS_PYTHON} "
        "to an executable interpreter."
    )
