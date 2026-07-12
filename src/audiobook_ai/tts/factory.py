"""TTS backend factory."""

from __future__ import annotations

from pathlib import Path

from audiobook_ai import config
from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.tts.fish_speech import FishSpeechBackend
from audiobook_ai.weights.manager import ModelManager


def get_tts_backend(
    name: str = config.DEFAULT_TTS_BACKEND,
    *,
    cache_dir: Path | str | None = None,
    manager: ModelManager | None = None,
    fish_model: str | None = None,
) -> TTSBackend:
    """Return a TTS backend by name (MVP: only ``fish-speech`` in-process)."""
    normalized = name.strip().lower()
    if normalized in {"fish-speech", "fish_speech", "fishspeech"}:
        return FishSpeechBackend(
            manager=manager,
            cache_dir=cache_dir,
            fish_model=fish_model or config.DEFAULT_FISH_MODEL,
        )
    raise ValueError(
        f"Unknown TTS backend {name!r}. MVP supports only 'fish-speech' "
        "(no Kokoro/Piper/XTTS/cloud)."
    )
