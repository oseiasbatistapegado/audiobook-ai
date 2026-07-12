"""Voice generation and registry package."""

from audiobook_ai.voice.book_id import compute_book_id
from audiobook_ai.voice.errors import VoiceGenerationError, VoiceLanguageError
from audiobook_ai.voice.generator import (
    NARRATOR_VOICE_PROFILE,
    BankVoiceGenerator,
    ParlerVoiceGenerator,
    derive_seed,
    get_voice_generator,
)
from audiobook_ai.voice.registry import VoiceRegistry

__all__ = [
    "BankVoiceGenerator",
    "NARRATOR_VOICE_PROFILE",
    "ParlerVoiceGenerator",
    "VoiceGenerationError",
    "VoiceLanguageError",
    "VoiceRegistry",
    "compute_book_id",
    "derive_seed",
    "get_voice_generator",
]
