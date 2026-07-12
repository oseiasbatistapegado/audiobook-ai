"""TTS request model."""

from __future__ import annotations

from pydantic import BaseModel, Field

from audiobook_ai.models.emotion import Emotion


class TTSRequest(BaseModel):
    """Input for a single TTS synthesis call."""

    text: str = Field(min_length=1)
    voice_id: str = Field(min_length=1, description="Local Fish Speech reference_id")
    emotion: Emotion = Emotion.NEUTRAL
    chapter_id: str | None = None
    segment_index: int | None = None
