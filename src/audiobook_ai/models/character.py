"""Character model with permanent id, aliases, and optional voice profile."""

from __future__ import annotations

from pydantic import BaseModel, Field

from audiobook_ai.models.voice import VoiceProfile


class Character(BaseModel):
    """A story character with a stable id."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    voice_profile: VoiceProfile | None = None
