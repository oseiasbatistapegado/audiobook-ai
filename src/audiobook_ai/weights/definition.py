"""Neutral pinned-weight identity for the ModelManager registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PinnedModel:
    """Versioned weight identity (logical id + HF repo + revision + files)."""

    logical_id: str
    repository: str
    revision: str
    required_files: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.revision.strip().lower() == "main":
            raise ValueError(
                f"PinnedModel.revision must not be 'main' "
                f"(logical_id={self.logical_id!r}); pin a tag or commit SHA"
            )
