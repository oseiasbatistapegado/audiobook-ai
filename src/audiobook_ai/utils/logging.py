"""Central logging helpers (never use print)."""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(
    *,
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> None:
    """Configure root logging for the CLI and pipeline."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger under the audiobook_ai namespace."""
    if not name.startswith("audiobook_ai"):
        name = f"audiobook_ai.{name}"
    return logging.getLogger(name)
