"""One spoken or narrated segment with emotion."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from audiobook_ai.models.emotion import Emotion, coerce_emotion


class Dialogue(BaseModel):
    """One spoken or narrated segment with emotion.

    The optional ``status`` field is used when QA fails:
    ``status="needs_review"`` means the unit was rejected and should be
    omitted from downstream TTS processing.
    """

    speaker_id: str | None = None
    speaker_name: str | None = None
    emotion: Emotion = Emotion.NEUTRAL
    text: str = Field(min_length=1)
    status: str | None = None
    rejection_reason: str | None = None

    @field_validator("emotion", mode="before")
    @classmethod
    def _coerce_emotion(cls, value: Any) -> Emotion:
        return coerce_emotion(value)

    @model_validator(mode="after")
    def require_speaker(self) -> Dialogue:
        """Require at least one of speaker_id or speaker_name, unless status is needs_review."""
        if self.status == "needs_review":
            return self
        if not self.speaker_id and not self.speaker_name:
            raise ValueError("dialogue requires speaker_id or speaker_name")
        return self
