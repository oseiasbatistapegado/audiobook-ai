"""Persistent voice registry under the app cache root (book-scoped)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.models.voice import (
    CANONICAL_VOICE_LANGUAGE,
    GeneratedVoice,
    VoiceProfile,
)
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.voice.errors import VoiceLanguageError
from audiobook_ai.weights.cache import resolve_cache_root

logger = get_logger(__name__)


class VoiceRegistry:
    """Disk-backed registry of materialized character voices.

    Layout: ``<cache>/voices/<book_id>/<character_id>/``
    """

    def __init__(self, cache_root: Path | str | None = None) -> None:
        self.cache_root = resolve_cache_root(cache_root)
        self.voices_root = self.cache_root / config.VOICES_CACHE_SUBDIR

    def voice_dir(self, book_id: str, character_id: str) -> Path:
        if not book_id or not character_id:
            raise ValueError("book_id and character_id are required")
        return self.voices_root / book_id / character_id

    def get(self, book_id: str, character_id: str) -> GeneratedVoice | None:
        """Return an existing valid pt-BR voice, or None."""
        directory = self.voice_dir(book_id, character_id)
        if not self.is_valid_pt_br(directory):
            return None
        meta = self._read_metadata(directory)
        text_path = self._reference_text_path(directory)
        assert text_path is not None
        profile = None
        raw_profile = meta.get("voice_profile")
        if isinstance(raw_profile, dict):
            try:
                profile = VoiceProfile.model_validate(raw_profile)
            except Exception:
                profile = None
        return GeneratedVoice(
            voice_id=str(meta.get("voice_id", character_id)),
            character_id=str(meta.get("character_id", character_id)),
            book_id=str(meta.get("book_id", book_id)),
            language=str(meta.get("language", CANONICAL_VOICE_LANGUAGE)),
            reference_wav=directory / "reference.wav",
            reference_text=text_path,
            generator=str(meta.get("generator", "registry")),
            generator_version=str(meta.get("generator_version", "1")),
            model_id=str(meta.get("model_id", "unknown")),
            seed=int(meta.get("seed", 0)),
            voice_profile=profile,
            base_voice_id=(
                str(meta["base_voice_id"]) if meta.get("base_voice_id") is not None else None
            ),
            metadata=meta,
        )

    def ensure(self, voice: GeneratedVoice) -> GeneratedVoice:
        """Idempotently materialize ``voice`` under the book-scoped registry.

        If a valid pt-BR voice already exists for ``book_id``/``character_id``,
        it is returned unchanged (persisted wins).
        """
        existing = self.get(voice.book_id, voice.character_id)
        if existing is not None:
            return existing

        if voice.language != CANONICAL_VOICE_LANGUAGE:
            raise VoiceLanguageError(voice.character_id, voice.language)

        if not voice.reference_wav.is_file():
            raise FileNotFoundError(
                f"GeneratedVoice missing reference.wav: {voice.reference_wav}"
            )

        dest = self.voice_dir(voice.book_id, voice.character_id)
        dest.mkdir(parents=True, exist_ok=True)

        dest_wav = dest / "reference.wav"
        shutil.copy2(voice.reference_wav, dest_wav)

        text_src = voice.reference_text
        if text_src.is_file():
            suffix = text_src.suffix.lower()
            dest_text = dest / ("reference.lab" if suffix == ".lab" else "reference.txt")
            if text_src.resolve() != dest_text.resolve():
                shutil.copy2(text_src, dest_text)
        else:
            dest_text = dest / "reference.lab"
            dest_text.write_text("", encoding="utf-8")

        profile_payload = None
        if voice.voice_profile is not None:
            profile_payload = voice.voice_profile.model_dump(mode="json", exclude_none=True)

        meta: dict[str, object] = {
            "language": CANONICAL_VOICE_LANGUAGE,
            "voice_id": voice.voice_id,
            "character_id": voice.character_id,
            "book_id": voice.book_id,
            "generator": voice.generator,
            "generator_version": voice.generator_version,
            "model_id": voice.model_id,
            "seed": voice.seed,
            "voice_profile": profile_payload,
            "base_voice_id": voice.base_voice_id,
            **{
                key: value
                for key, value in voice.metadata.items()
                if key
                not in {
                    "language",
                    "voice_id",
                    "character_id",
                    "book_id",
                    "generator",
                    "generator_version",
                    "model_id",
                    "seed",
                    "voice_profile",
                    "base_voice_id",
                }
            },
        }
        (dest / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "materialized voice book_id=%s character_id=%s generator=%s path=%s",
            voice.book_id,
            voice.character_id,
            voice.generator,
            dest,
        )
        stored = self.get(voice.book_id, voice.character_id)
        if stored is None:
            raise RuntimeError(
                f"failed to materialize book_id={voice.book_id!r} "
                f"character_id={voice.character_id!r}"
            )
        return stored

    def is_valid_pt_br(self, directory: Path) -> bool:
        if not directory.is_dir():
            return False
        if not (directory / "reference.wav").is_file():
            return False
        if self._reference_text_path(directory) is None:
            return False
        meta = self._read_metadata(directory)
        language = meta.get("language")
        return language == CANONICAL_VOICE_LANGUAGE

    def missing_character_ids(
        self, book_id: str, character_ids: list[str] | set[str]
    ) -> list[str]:
        """Return character ids that do not yet have a valid registry entry."""
        missing: list[str] = []
        for character_id in character_ids:
            if self.get(book_id, character_id) is None:
                missing.append(character_id)
        return missing

    @staticmethod
    def _reference_text_path(directory: Path) -> Path | None:
        for name in ("reference.lab", "reference.txt"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _read_metadata(directory: Path) -> dict[str, object]:
        meta_path = directory / "metadata.json"
        if not meta_path.is_file():
            return {}
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}
