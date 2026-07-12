"""Story state persisted in story.json."""

from __future__ import annotations

from pydantic import BaseModel, Field

from audiobook_ai.models.character import Character


class StoryState(BaseModel):
    """Minimal persistent story state: characters and fixed voice map."""

    characters: list[Character] = Field(default_factory=list)
    voice_map: dict[str, str] = Field(
        default_factory=dict,
        description="character_id → local Fish Speech reference_id",
    )
