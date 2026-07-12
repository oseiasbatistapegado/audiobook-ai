"""Model weight management (download, cache, validation)."""

from __future__ import annotations

from audiobook_ai.weights.cache import resolve_cache_root
from audiobook_ai.weights.fish import (
    DEFAULT_FISH_MODEL_ALIAS,
    FISH_SPEECH_ID,
    FishSpeechModel,
    list_fish_model_aliases,
    resolve_fish_model,
)
from audiobook_ai.weights.manager import ModelHandle, ModelManager

__all__ = [
    "DEFAULT_FISH_MODEL_ALIAS",
    "FISH_SPEECH_ID",
    "FishSpeechModel",
    "ModelHandle",
    "ModelManager",
    "list_fish_model_aliases",
    "resolve_cache_root",
    "resolve_fish_model",
]
