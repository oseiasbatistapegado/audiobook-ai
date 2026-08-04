"""TTS backends (Qwen3-TTS Voice Clone)."""

from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.tts.factory import get_tts_backend
from audiobook_ai.tts.qwen3_tts import Qwen3TTSBackend

__all__ = ["Qwen3TTSBackend", "TTSBackend", "get_tts_backend"]
