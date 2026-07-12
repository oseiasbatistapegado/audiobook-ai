"""Dialogue segment produced by the LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from audiobook_ai.models.emotion import Emotion


class Dialogue(BaseModel):
    """One spoken or narrated segment with emotion."""

    speaker_id: str | None = None
    speaker_name: str | None = None
    emotion: Emotion
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_speaker(self) -> Dialogue:
        """Require at least one of speaker_id or speaker_name."""
        if not self.speaker_id and not self.speaker_name:
            raise ValueError("dialogue requires speaker_id or speaker_name")
        return self
