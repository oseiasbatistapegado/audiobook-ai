"""Stable cast fingerprint for LLM cache keys (not full story dump)."""

from __future__ import annotations

import hashlib

from audiobook_ai.models.story import StoryState


def story_cast_fingerprint(story_state: StoryState) -> str:
    """Hash sorted character ids and aliases (order-independent, voice_map-agnostic)."""
    parts: list[str] = []
    for character in sorted(story_state.characters, key=lambda c: c.id):
        aliases = ",".join(sorted(a.strip() for a in character.aliases if a.strip()))
        parts.append(f"{character.id}|{aliases}")
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
