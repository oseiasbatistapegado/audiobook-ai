"""TTSBackend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from audiobook_ai.models.audio import AudioSegment
from audiobook_ai.models.tts import TTSRequest


class TTSBackend(ABC):
    """Synthesize speech for a single request."""

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> AudioSegment:
        """Generate audio for ``request``."""

    def release(self) -> None:
        """Release GPU/host resources held by the backend (default: no-op)."""

    def release(self) -> None:
        """Release GPU/host resources held by the backend (default: no-op)."""
