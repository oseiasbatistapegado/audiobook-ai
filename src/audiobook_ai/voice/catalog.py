"""Discover packaged pt-BR base voices from assets/voices."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.models.voice import CANONICAL_VOICE_LANGUAGE, VoiceProfile
from audiobook_ai.tts.voices import project_assets_voices_root
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

NARRATOR_ROLE = "narrator"
CHARACTER_ROLE = "character"


@dataclass(frozen=True)
class BaseVoice:
    """A packaged base voice eligible for assignment."""

    voice_id: str
    path: Path
    language: str
    gender: str | None = None
    age_range: str | None = None
    tags: tuple[str, ...] = ()
    role: str = CHARACTER_ROLE
    license: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def is_narrator(self) -> bool:
        return self.role == NARRATOR_ROLE or self.voice_id == config.NARRATOR_VOICE_ID

    @property
    def reference_wav(self) -> Path:
        return self.path / "reference.wav"

    @property
    def reference_text(self) -> Path:
        lab = self.path / "reference.lab"
        if lab.is_file():
            return lab
        return self.path / "reference.txt"


def load_voice_metadata(voice_dir: Path) -> dict[str, object]:
    meta_path = voice_dir / "metadata.json"
    if not meta_path.is_file():
        return {}
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("invalid voice metadata path=%s error=%s", meta_path, exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def _has_reference_audio(voice_dir: Path) -> bool:
    if (voice_dir / "reference.wav").is_file():
        return True
    return any(voice_dir.glob("*.wav"))


def discover_base_voices(
    *,
    assets_root: Path | None = None,
    require_pt_br: bool = True,
) -> list[BaseVoice]:
    """Discover base voices from the packaged catalog (filesystem)."""
    root = assets_root if assets_root is not None else project_assets_voices_root()
    if not root.is_dir():
        return []

    found: list[BaseVoice] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not _has_reference_audio(child):
            continue
        meta = load_voice_metadata(child)
        language = meta.get("language")
        language_str = str(language) if language is not None else None
        if require_pt_br and language_str != CANONICAL_VOICE_LANGUAGE:
            logger.debug(
                "skipping base voice without pt-BR metadata voice_id=%s language=%s",
                child.name,
                language_str,
            )
            continue

        tags_raw = meta.get("tags") or []
        tags = tuple(str(t) for t in tags_raw) if isinstance(tags_raw, list) else ()
        role = str(meta.get("role") or CHARACTER_ROLE)
        if child.name == config.NARRATOR_VOICE_ID:
            role = NARRATOR_ROLE

        found.append(
            BaseVoice(
                voice_id=child.name,
                path=child,
                language=language_str or CANONICAL_VOICE_LANGUAGE,
                gender=str(meta["gender"]) if meta.get("gender") is not None else None,
                age_range=(
                    str(meta["age_range"]) if meta.get("age_range") is not None else None
                ),
                tags=tags,
                role=role,
                license=str(meta["license"]) if meta.get("license") is not None else None,
                metadata=meta,
            )
        )
    return found


def character_pool(bases: list[BaseVoice]) -> list[BaseVoice]:
    """Return non-narrator bases for character assignment."""
    return [base for base in bases if not base.is_narrator]


def score_base_for_profile(base: BaseVoice, profile: VoiceProfile | None) -> int:
    """Higher score = better match; unknown fields are ignored."""
    if profile is None:
        return 0
    score = 0
    gender = (profile.gender or "").strip().casefold()
    if gender and base.gender and gender == base.gender.casefold():
        score += 10
    elif gender and base.gender and gender != base.gender.casefold():
        score -= 5

    age = (profile.age_range or "").strip().casefold()
    if age and base.age_range and age == base.age_range.casefold():
        score += 5
    elif age and age in {t.casefold() for t in base.tags}:
        score += 3

    for tag in profile.personality:
        if tag and tag.casefold() in {t.casefold() for t in base.tags}:
            score += 1
    return score
