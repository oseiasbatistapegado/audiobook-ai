"""Pinned Qwen3-TTS 0.6B Base weight registry (never floating ``main``)."""

from __future__ import annotations

from audiobook_ai.weights.definition import PinnedModel

# Logical cache id under ~/.cache/audiobook-ai/<logical_id>/
QWEN3_TTS_ID: str = "qwen3-tts"

# SHA from huggingface model_info (Qwen/Qwen3-TTS-12Hz-0.6B-Base); never "main".
QWEN3_TTS_REVISION: str = "5d83992436eae1d760afd27aff78a71d676296fc"
QWEN3_TTS_REPOSITORY: str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
QWEN3_TTS_REQUIRED_FILES: tuple[str, ...] = (
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "preprocessor_config.json",
    "speech_tokenizer/config.json",
    "speech_tokenizer/configuration.json",
    "speech_tokenizer/model.safetensors",
    "speech_tokenizer/preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
)

# Official generate_voice_clone language token for Portuguese (API of qwen-tts).
QWEN3_TTS_LANGUAGE: str = "Portuguese"


def qwen3_tts_model() -> PinnedModel:
    """Return the pinned Qwen3-TTS Base definition."""
    return PinnedModel(
        logical_id=QWEN3_TTS_ID,
        repository=QWEN3_TTS_REPOSITORY,
        revision=QWEN3_TTS_REVISION,
        required_files=QWEN3_TTS_REQUIRED_FILES,
    )


QWEN3_TTS_MODEL: PinnedModel = qwen3_tts_model()
