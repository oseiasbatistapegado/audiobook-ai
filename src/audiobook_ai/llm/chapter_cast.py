"""Chapter cast helpers: speaker set, merge, fingerprint, story merge."""

from __future__ import annotations

import hashlib

from audiobook_ai import config
from audiobook_ai.models.cast import (
    ChapterCastEntry,
    ChapterParticipation,
    LLMCastDiscoveryResponse,
)
from audiobook_ai.models.character import Character
from audiobook_ai.models.llm import StoryUpdates

_SPEAKING = frozenset(
    {
        ChapterParticipation.SPEAKER,
        ChapterParticipation.POSSIBLE_SPEAKER,
    }
)


def is_speaking_participation(participation: ChapterParticipation) -> bool:
    return participation in _SPEAKING


def speaker_set_from_cast(entries: list[ChapterCastEntry]) -> set[str]:
    """Closed speaker set: narrator ∪ chapter speakers / possible_speakers."""
    allowed = {config.NARRATOR_VOICE_ID, "narrator", "narrador"}
    for entry in entries:
        if is_speaking_participation(entry.participation):
            allowed.add(entry.id)
    return allowed


def chapter_cast_fingerprint(entries: list[ChapterCastEntry]) -> str:
    """Stable fingerprint of chapter cast (id + participation + aliases)."""
    parts: list[str] = []
    for entry in sorted(entries, key=lambda e: e.id):
        aliases = ",".join(sorted(a.strip() for a in entry.aliases if a.strip()))
        parts.append(f"{entry.id}|{entry.participation.value}|{aliases}")
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cast_to_story_updates(discovery: LLMCastDiscoveryResponse) -> StoryUpdates:
    """Project discovery identities into StoryUpdates (drops participation).

    Cast Discovery is now "cold" — no voice_profile from Pass 1.
    """
    characters: list[Character] = []
    for entry in discovery.characters:
        characters.append(
            Character(
                id=entry.id,
                name=entry.name,
                aliases=list(entry.aliases),
                voice_profile=None,
            )
        )
    return StoryUpdates(characters=characters)


def merge_cast_discoveries(
    discoveries: list[LLMCastDiscoveryResponse],
) -> LLMCastDiscoveryResponse:
    """Merge partial cast discoveries (chunk coverage) by character id."""
    by_id: dict[str, ChapterCastEntry] = {}
    rank = {
        ChapterParticipation.MENTIONED: 0,
        ChapterParticipation.POSSIBLE_SPEAKER: 1,
        ChapterParticipation.SPEAKER: 2,
    }
    for discovery in discoveries:
        for entry in discovery.characters:
            existing = by_id.get(entry.id)
            if existing is None:
                by_id[entry.id] = entry.model_copy(deep=True)
                continue
            merged = existing.model_copy(deep=True)
            merged.aliases = list(
                dict.fromkeys([*merged.aliases, *entry.aliases, entry.name])
            )
            if entry.name.strip() and merged.name.casefold() != entry.name.casefold():
                merged.aliases = list(
                    dict.fromkeys([*merged.aliases, entry.name])
                )
            if rank[entry.participation] > rank[merged.participation]:
                merged.participation = entry.participation
            by_id[entry.id] = merged
    return LLMCastDiscoveryResponse(characters=list(by_id.values()))


def restrict_pass2_story_updates(
    updates: StoryUpdates,
    *,
    known_ids: set[str],
) -> StoryUpdates:
    """Drop Pass-2 character creations; keep aliases only for known ids."""
    aliases = {
        cid: list(vals)
        for cid, vals in updates.aliases.items()
        if cid in known_ids
    }
    return StoryUpdates(characters=[], aliases=aliases)
