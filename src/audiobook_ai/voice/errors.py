"""Voice generation / registry errors."""

from __future__ import annotations


class VoiceGenerationError(RuntimeError):
    """Raised when automatic voice assignment fails without a usable voice_id."""

    def __init__(self, character_id: str, reason: str) -> None:
        self.character_id = character_id
        self.reason = reason
        super().__init__(f"voice generation failed for character_id={character_id!r}: {reason}")


class VoiceLanguageError(VoiceGenerationError):
    """Raised when a voice is not valid pt-BR for the automatic flow."""

    def __init__(self, character_id: str, language: str | None) -> None:
        lang = language if language is not None else "<missing>"
        super().__init__(character_id, f"language must be pt-BR, got {lang!r}")
        self.language = language
