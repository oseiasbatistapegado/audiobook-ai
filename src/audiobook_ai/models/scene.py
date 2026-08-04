"""Scene segmentation models."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field


class Scene(BaseModel):
    """A narrative scene within a chapter."""

    scene_id: str = Field(min_length=1)
    units: list[str] = Field(default_factory=list)
    text: str = ""

    def compute_text_hash(self) -> str:
        """Deterministic hash of scene text (for cache keys)."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    def add_unit(self, unit_text: str) -> None:
        """Append a text unit to the scene."""
        self.units.append(unit_text)
        if self.text:
            self.text += "\n\n"
        self.text += unit_text
