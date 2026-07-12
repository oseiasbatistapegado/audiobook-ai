"""LLM response models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from audiobook_ai.models.character import Character
from audiobook_ai.models.dialogue import Dialogue


class StoryUpdates(BaseModel):
    """Minimal story updates from a chapter interpretation."""

    characters: list[Character] = Field(default_factory=list)
    aliases: dict[str, list[str]] = Field(
        default_factory=dict,
        description="character_id → new aliases to merge",
    )


class LLMChapterResponse(BaseModel):
    """Validated JSON-only response for one chapter."""

    dialogues: list[Dialogue] = Field(min_length=1)
    story_updates: StoryUpdates = Field(default_factory=StoryUpdates)
