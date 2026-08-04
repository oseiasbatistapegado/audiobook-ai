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

    def synthesize_batch(self, requests: list[TTSRequest]) -> list[AudioSegment]:
        """Generate audio for multiple requests (default: sequential synthesize)."""
        return [self.synthesize(request) for request in requests]

    def release(self) -> None:
        """Release GPU/host resources held by the backend (default: no-op)."""
