"""TTS backends (Fish Speech local only in MVP)."""

from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.tts.factory import get_tts_backend
from audiobook_ai.tts.fish_speech import FishSpeechBackend

__all__ = ["FishSpeechBackend", "TTSBackend", "get_tts_backend"]
