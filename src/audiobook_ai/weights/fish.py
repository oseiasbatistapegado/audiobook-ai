"""Pinned Fish Speech open-weight registry (never floating ``main``)."""

from __future__ import annotations

from dataclasses import dataclass, field

# CLI / product aliases (not cache directory names).
DEFAULT_FISH_MODEL_ALIAS: str = "s1-mini"

# Logical cache ids under ~/.cache/audiobook-ai/<logical_id>/
FISH_S1_MINI_ID: str = "fish-s1-mini"
FISH_S2_PRO_ID: str = "fish-s2-pro"
# Default logical id for ModelManager / TTS when no alias is resolved.
FISH_SPEECH_ID: str = FISH_S1_MINI_ID

# --- s1-mini (default) ---
# SHA from huggingface model_info (fishaudio/s1-mini); never use branch "main".
FISH_S1_MINI_REVISION: str = "f4b445029346701e082b60bb63fcc2d1bb17a0e2"
FISH_S1_MINI_REPOSITORY: str = "fishaudio/openaudio-s1-mini"
FISH_S1_MINI_REQUIRED_FILES: tuple[str, ...] = (
    "codec.pth",
    "config.json",
    "model.pth",
    "special_tokens.json",
    "tokenizer.tiktoken",
)

# --- s2-pro ---
FISH_S2_PRO_REVISION: str = "1de9996b6be38b745688de084d87a5633f714e4e"
FISH_S2_PRO_REPOSITORY: str = "fishaudio/s2-pro"
FISH_S2_PRO_REQUIRED_FILES: tuple[str, ...] = (
    "codec.pth",
    "config.json",
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "chat_template.jinja",
)

# Back-compat names used by older tests/imports (point at the product default).
FISH_SPEECH_REVISION: str = FISH_S1_MINI_REVISION
FISH_SPEECH_REPOSITORY: str = FISH_S1_MINI_REPOSITORY
FISH_SPEECH_REQUIRED_FILES: tuple[str, ...] = FISH_S1_MINI_REQUIRED_FILES


@dataclass(frozen=True, slots=True)
class FishSpeechModel:
    """Versioned Fish Speech weight identity for the ModelManager."""

    alias: str
    logical_id: str
    repository: str
    revision: str
    required_files: tuple[str, ...]
    # Presets applied when the user did not override chunk/load knobs.
    tts_max_chunk_chars: int
    before_load_target_mib: int

    def __post_init__(self) -> None:
        if self.revision.strip().lower() == "main":
            raise ValueError(
                "FishSpeechModel.revision must not be 'main'; pin a tag or commit SHA"
            )


def _s1_mini() -> FishSpeechModel:
    from audiobook_ai import config

    return FishSpeechModel(
        alias="s1-mini",
        logical_id=FISH_S1_MINI_ID,
        repository=FISH_S1_MINI_REPOSITORY,
        revision=FISH_S1_MINI_REVISION,
        required_files=FISH_S1_MINI_REQUIRED_FILES,
        tts_max_chunk_chars=config.TTS_MAX_CHUNK_CHARS,
        before_load_target_mib=config.FISH_BEFORE_LOAD_TARGET_MIB,
    )


def _s2_pro() -> FishSpeechModel:
    from audiobook_ai import config

    return FishSpeechModel(
        alias="s2-pro",
        logical_id=FISH_S2_PRO_ID,
        repository=FISH_S2_PRO_REPOSITORY,
        revision=FISH_S2_PRO_REVISION,
        required_files=FISH_S2_PRO_REQUIRED_FILES,
        tts_max_chunk_chars=config.FISH_S2_PRO_TTS_MAX_CHUNK_CHARS,
        before_load_target_mib=config.FISH_S2_PRO_BEFORE_LOAD_TARGET_MIB,
    )


def fish_model_registry() -> dict[str, FishSpeechModel]:
    """Return alias → definition map (built lazily so config defaults apply)."""
    models = (_s1_mini(), _s2_pro())
    return {m.alias: m for m in models}


def list_fish_model_aliases() -> tuple[str, ...]:
    return tuple(sorted(fish_model_registry()))


def resolve_fish_model(alias: str | None = None) -> FishSpeechModel:
    """Resolve a CLI/env alias to a pinned FishSpeechModel.

    Raises ``ValueError`` with the valid alias list when unknown.
    """
    key = (alias or DEFAULT_FISH_MODEL_ALIAS).strip().lower()
    registry = fish_model_registry()
    try:
        return registry[key]
    except KeyError as exc:
        valid = ", ".join(sorted(registry))
        raise ValueError(
            f"Unknown fish model {alias!r}. Valid --fish-model aliases: {valid}"
        ) from exc
