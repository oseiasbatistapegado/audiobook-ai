"""Character resolution and immutable voice assignment."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.models.character import Character
from audiobook_ai.models.llm import StoryUpdates
from audiobook_ai.models.story import StoryState
from audiobook_ai.models.voice import CharacterProfile, VoiceProfile
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.voice.errors import VoiceGenerationError
from audiobook_ai.voice.generator import (
    NARRATOR_VOICE_PROFILE,
    VoiceGenerator,
    get_voice_generator,
)
from audiobook_ai.voice.registry import VoiceRegistry

logger = get_logger(__name__)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "character"


def resolve_character_id(
    state: StoryState,
    *,
    speaker_id: str | None = None,
    speaker_name: str | None = None,
) -> str:
    """Resolve a speaker to a permanent character id."""
    if speaker_id:
        for character in state.characters:
            if character.id == speaker_id:
                return character.id
        return speaker_id

    if not speaker_name:
        raise ValueError("speaker_id or speaker_name is required")

    needle = speaker_name.strip().casefold()
    for character in state.characters:
        names = [character.name, *character.aliases]
        if any(name.strip().casefold() == needle for name in names):
            return character.id

    new_id = _slug(speaker_name)
    existing_ids = {character.id for character in state.characters}
    candidate = new_id
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{new_id}-{suffix}"
        suffix += 1

    state.characters.append(Character(id=candidate, name=speaker_name.strip(), aliases=[]))
    logger.info("registered character id=%s name=%s", candidate, speaker_name)
    return candidate


def apply_story_updates(state: StoryState, updates: StoryUpdates) -> StoryState:
    """Merge minimal story updates into ``state`` (mutates and returns)."""
    by_id = {character.id: character for character in state.characters}

    for character in updates.characters:
        existing = by_id.get(character.id)
        if existing is None:
            state.characters.append(character)
            by_id[character.id] = character
            continue
        merged_aliases = list(
            dict.fromkeys([*existing.aliases, *character.aliases, character.name])
        )
        if existing.name.casefold() != character.name.casefold():
            merged_aliases = list(dict.fromkeys([*merged_aliases, character.name]))
        existing.aliases = [alias for alias in merged_aliases if alias != existing.name]
        if character.voice_profile is not None and existing.voice_profile is None:
            existing.voice_profile = character.voice_profile

    for character_id, aliases in updates.aliases.items():
        existing = by_id.get(character_id)
        if existing is None:
            continue
        existing.aliases = list(dict.fromkeys([*existing.aliases, *aliases]))

    return state


def _profile_for(state: StoryState, character_id: str) -> CharacterProfile:
    character = next((item for item in state.characters if item.id == character_id), None)
    voice_profile: VoiceProfile | None = character.voice_profile if character else None
    name = character.name if character else None
    if character_id == config.NARRATOR_VOICE_ID or (
        name and name.strip().casefold() == "narrator"
    ):
        return CharacterProfile(
            character_id=config.NARRATOR_VOICE_ID,
            name=name or "Narrator",
            voice_profile=voice_profile or NARRATOR_VOICE_PROFILE,
        )
    return CharacterProfile(
        character_id=character_id,
        name=name,
        voice_profile=voice_profile,
    )


def ensure_voice(
    state: StoryState,
    character_id: str,
    *,
    book_id: str,
    cache_root: Path | str | None = None,
    registry: VoiceRegistry | None = None,
    generator: VoiceGenerator | None = None,
    generator_name: str | None = None,
) -> str:
    """Return the fixed voice for ``character_id``, generating once if needed.

    On failure, does **not** write stock/share/english/symbolic ids into
    ``voice_map``.
    """
    if not book_id:
        raise VoiceGenerationError(character_id, "book_id is required")

    existing = state.voice_map.get(character_id)
    if existing is not None:
        return existing

    voice_registry = registry or VoiceRegistry(cache_root=cache_root)

    cached = voice_registry.get(book_id, character_id)
    if cached is not None:
        state.voice_map[character_id] = cached.voice_id
        logger.info(
            "assigned voice from registry book_id=%s character_id=%s voice_id=%s",
            book_id,
            character_id,
            cached.voice_id,
        )
        return cached.voice_id

    voice_gen = generator or get_voice_generator(
        generator_name, registry=voice_registry
    )
    profile = _profile_for(state, character_id)

    try:
        generated = voice_gen.generate_voice(profile, book_id=book_id)
        # Refuse symbolic success without a real reference file.
        if not generated.reference_wav.is_file():
            raise VoiceGenerationError(
                character_id,
                "generator returned voice without usable reference.wav",
            )
        if generated.language != config.VOICE_LANGUAGE:
            raise VoiceGenerationError(
                character_id,
                f"generator returned non-pt-BR language={generated.language!r}",
            )
        stored = voice_registry.ensure(generated)
    except VoiceGenerationError:
        # Do not pollute voice_map / do not stock-share / do not fall back to EN.
        raise

    state.voice_map[character_id] = stored.voice_id
    logger.info(
        "assigned voice book_id=%s character_id=%s voice_id=%s generator=%s seed=%s",
        book_id,
        character_id,
        stored.voice_id,
        stored.generator,
        stored.seed,
    )
    return stored.voice_id


def ensure_voices_batch(
    state: StoryState,
    character_ids: list[str],
    *,
    book_id: str,
    cache_root: Path | str | None = None,
    registry: VoiceRegistry | None = None,
    generator: VoiceGenerator | None = None,
    generator_name: str | None = None,
) -> None:
    """Generate all missing voices for ``book_id``, then unload Voice Design.

    Intended before Fish Speech load so both models are not resident.
    """
    voice_registry = registry or VoiceRegistry(cache_root=cache_root)
    voice_gen = generator or get_voice_generator(
        generator_name, registry=voice_registry
    )
    try:
        for character_id in character_ids:
            if character_id in state.voice_map:
                continue
            ensure_voice(
                state,
                character_id,
                book_id=book_id,
                cache_root=cache_root,
                registry=voice_registry,
                generator=voice_gen,
            )
    finally:
        unload = getattr(voice_gen, "unload", None)
        if callable(unload):
            unload()
