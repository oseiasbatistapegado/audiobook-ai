"""Audio segment model referencing bytes or a file path."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class AudioSegment(BaseModel):
    """A synthesized audio segment ready for merge."""

    path: Path | None = None
    data: bytes | None = None
    format: str = Field(default="wav", min_length=1)
    chapter_id: str | None = None
    segment_index: int | None = None

    @model_validator(mode="after")
    def require_path_or_data(self) -> AudioSegment:
        """Require either on-disk path or in-memory bytes."""
        if self.path is None and self.data is None:
            raise ValueError("AudioSegment requires path or data")
        if self.data is not None and len(self.data) == 0:
            raise ValueError("AudioSegment data must not be empty")
        return self
