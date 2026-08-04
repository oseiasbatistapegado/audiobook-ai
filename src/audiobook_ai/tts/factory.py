"""TTS backend factory."""

from __future__ import annotations

from pathlib import Path

from audiobook_ai import config
from audiobook_ai.tts.base import TTSBackend
from audiobook_ai.tts.qwen3_tts import Qwen3TTSBackend
from audiobook_ai.weights.manager import ModelManager

_SUPPORTED = frozenset({"qwen3-tts", "qwen3tts"})
_REJECTED = frozenset(
    {
        "fish",
        "fish-speech",
        "fish_speech",
        "fishspeech",
        "s1-mini",
        "s2-pro",
        "cosyvoice",
        "cosyvoice3",
    }
)


def get_tts_backend(
    name: str = config.DEFAULT_TTS_BACKEND,
    *,
    cache_dir: Path | str | None = None,
    manager: ModelManager | None = None,
    fish_model: str | None = None,
) -> TTSBackend:
    """Return the product TTS backend (only ``qwen3-tts``).

    ``fish_model`` is accepted for call-site compatibility during migration and
    ignored; Fish backends are rejected.
    """
    del fish_model  # no dual-backend / Fish alias routing
    normalized = name.strip().lower().replace("_", "-")
    if normalized in _SUPPORTED:
        return Qwen3TTSBackend(manager=manager, cache_dir=cache_dir)
    if normalized in _REJECTED:
        raise ValueError(
            f"TTS backend {name!r} is no longer supported. "
            "Only 'qwen3-tts' (alias 'qwen3tts') is available."
        )
    raise ValueError(
        f"Unknown TTS backend {name!r}. Only 'qwen3-tts' (alias 'qwen3tts') "
        "is supported (no Fish/CosyVoice/cloud)."
    )
