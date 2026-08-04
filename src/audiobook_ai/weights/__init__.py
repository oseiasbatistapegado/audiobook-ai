"""Model weight management (download, cache, validation)."""

from __future__ import annotations

from audiobook_ai.weights.cache import resolve_cache_root
from audiobook_ai.weights.definition import PinnedModel
from audiobook_ai.weights.manager import ModelHandle, ModelManager
from audiobook_ai.weights.qwen3_tts import (
    QWEN3_TTS_ID,
    QWEN3_TTS_LANGUAGE,
    QWEN3_TTS_MODEL,
    QWEN3_TTS_REPOSITORY,
    QWEN3_TTS_REQUIRED_FILES,
    QWEN3_TTS_REVISION,
)

__all__ = [
    "ModelHandle",
    "ModelManager",
    "PinnedModel",
    "QWEN3_TTS_ID",
    "QWEN3_TTS_LANGUAGE",
    "QWEN3_TTS_MODEL",
    "QWEN3_TTS_REPOSITORY",
    "QWEN3_TTS_REQUIRED_FILES",
    "QWEN3_TTS_REVISION",
    "resolve_cache_root",
]
