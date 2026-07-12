"""Voice profile and generated-voice models."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

CANONICAL_VOICE_LANGUAGE: str = "pt-BR"


class VoiceProfile(BaseModel):
    """Semantic hints for automatic voice assignment (optional from LLM)."""

    gender: str | None = None
    age_range: str | None = None
    pitch: str | None = None
    pace: str | None = None
    energy: str | None = None
    texture: str | None = None
    personality: list[str] = Field(default_factory=list)


class CharacterProfile(BaseModel):
    """Character identity plus optional voice hints for the VoiceGenerator."""

    character_id: str = Field(min_length=1)
    name: str | None = None
    voice_profile: VoiceProfile | None = None
    language: str = CANONICAL_VOICE_LANGUAGE


class GeneratedVoice(BaseModel):
    """Result of VoiceGenerator: a reusable local reference identity."""

    voice_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    language: str = CANONICAL_VOICE_LANGUAGE
    reference_wav: Path
    reference_text: Path
    generator: str = Field(min_length=1)
    generator_version: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    seed: int
    voice_profile: VoiceProfile | None = None
    # Legacy / bank-only provenance (not used by generative product path).
    base_voice_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
