"""Work-dir layout under ``out/`` (or a custom ``--work-dir``).

Resumable artifacts for a book live under ``<work_dir>/<book_id>/``.
The user-controlled output M4B path does NOT determine ``book_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audiobook_ai import config


@dataclass(frozen=True, slots=True)
class WorkDirLayout:
    """Resolved paths for pipeline artifacts (work-dir root)."""

    root: Path
    story_path: Path
    chapters_dir: Path
    cache_dir: Path
    logs_dir: Path

    def default_output_path(self) -> Path:
        """Return the default M4B path under this work-dir."""
        return self.root / config.DEFAULT_OUTPUT_NAME

    def book_layout(self, book_id: str) -> BookWorkLayout:
        """Return book-scoped paths under ``root/<book_id>/``."""
        return ensure_book_work_dir(self.root, book_id)


@dataclass(frozen=True, slots=True)
class BookWorkLayout:
    """Book-scoped resumable artifact tree: ``work/<book_id>/``."""

    book_id: str
    root: Path
    story_path: Path
    manifest_path: Path
    audio_dir: Path
    chapters_dir: Path
    jobs_dir: Path
    logs_dir: Path


def ensure_work_dir(work_dir: Path | str | None = None) -> WorkDirLayout:
    """Create ``out/`` (or custom work-dir) and standard subdirectories."""
    root = Path(work_dir) if work_dir is not None else config.DEFAULT_WORK_DIR
    root = root.resolve() if root.is_absolute() else root

    chapters_dir = root / config.CHAPTERS_SUBDIR
    cache_dir = root / config.CACHE_SUBDIR
    logs_dir = root / config.LOGS_SUBDIR

    for path in (root, chapters_dir, cache_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)

    return WorkDirLayout(
        root=root,
        story_path=root / config.STORY_FILENAME,
        chapters_dir=chapters_dir,
        cache_dir=cache_dir,
        logs_dir=logs_dir,
    )


def ensure_book_work_dir(work_dir: Path | str, book_id: str) -> BookWorkLayout:
    """Create ``<work_dir>/<book_id>/`` with audio/, jobs/, logs/, chapters/."""
    if not book_id or not book_id.strip():
        raise ValueError("book_id must be non-empty")
    root = Path(work_dir) / book_id
    audio_dir = root / config.AUDIO_SUBDIR
    chapters_dir = root / config.CHAPTERS_SUBDIR
    jobs_dir = root / config.JOBS_SUBDIR
    logs_dir = root / config.LOGS_SUBDIR
    for path in (root, audio_dir, chapters_dir, jobs_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    return BookWorkLayout(
        book_id=book_id,
        root=root,
        story_path=root / config.STORY_FILENAME,
        manifest_path=root / config.MANIFEST_FILENAME,
        audio_dir=audio_dir,
        chapters_dir=chapters_dir,
        jobs_dir=jobs_dir,
        logs_dir=logs_dir,
    )
