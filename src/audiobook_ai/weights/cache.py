"""Cache root resolution and per-model layout / file locks."""

from __future__ import annotations

import os
from pathlib import Path

from filelock import FileLock

from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CACHE_DIRNAME: str = ".cache/audiobook-ai"
ENV_CACHE_DIR: str = "AUDIOBOOK_AI_CACHE_DIR"
LOCK_FILENAME: str = ".download.lock"


def resolve_cache_root(
    cache_dir: Path | str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> Path:
    """Resolve cache root: ``cache_dir`` > ``AUDIOBOOK_AI_CACHE_DIR`` > ``~/.cache/audiobook-ai/``."""
    if cache_dir is not None:
        return Path(cache_dir).expanduser().resolve()

    environ = env if env is not None else os.environ
    from_env = environ.get(ENV_CACHE_DIR)
    if from_env:
        return Path(from_env).expanduser().resolve()

    return (Path.home() / DEFAULT_CACHE_DIRNAME).resolve()


def model_dir(cache_root: Path, logical_id: str) -> Path:
    """Return ``<cache_root>/<logical_id>/``."""
    return Path(cache_root) / logical_id


def download_lock(model_path: Path) -> FileLock:
    """File lock that serializes concurrent downloads for one model directory."""
    model_path.mkdir(parents=True, exist_ok=True)
    lock_path = model_path / LOCK_FILENAME
    return FileLock(str(lock_path))
