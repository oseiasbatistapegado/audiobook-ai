"""LLMBackend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from audiobook_ai.models.book import Chapter
from audiobook_ai.models.llm import LLMChapterResponse
from audiobook_ai.models.story import StoryState


class LLMBackend(ABC):
    """Interpret a chapter into validated structured JSON."""

    @abstractmethod
    def interpret_chapter(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> LLMChapterResponse:
        """Return a Pydantic-validated chapter interpretation."""

    def unload(self) -> None:
        """Release the model from host/GPU memory if applicable (default: no-op)."""
