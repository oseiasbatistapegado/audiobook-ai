"""Character profile manager — immutable cross-chapter profiles.

The CharacterProfile is cacheable by ``character_id`` (not by chapter),
persisted as ``character_profiles.json`` in the book work directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from audiobook_ai.models.cast import CharacterProfile


def resolve_character_profile(
    character_id: str,
    name: str,
    aliases: list[str],
    *,
    cache: dict[str, CharacterProfile] | None = None,
    gender: str | None = None,
    role: str | None = None,
) -> CharacterProfile:
    """Resolve or create a CharacterProfile for the given character.

    If *cache* is provided and the character already exists, returns the
    cached profile (immutable, cross-chapter persistence).

    Args:
        character_id: Stable character identifier.
        name: Display name.
        aliases: Known aliases.
        cache: Optional cache dict keyed by character_id.
        gender: Gender hint (optional).
        role: Role (POV / secondary / teacher, default ``secondary``).

    Returns:
        A ``CharacterProfile`` — either from cache or newly created.
    """
    if cache is not None and character_id in cache:
        return cache[character_id]

    profile = CharacterProfile(
        id=character_id,
        name=name,
        aliases=aliases,
        gender=gender,
        role=role or "secondary",
        known_names=[name, *aliases],
    )
    if cache is not None:
        cache[character_id] = profile
    return profile


def load_character_profiles(path: Path) -> dict[str, CharacterProfile]:
    """Load character profiles from a JSON file.

    Args:
        path: Path to ``character_profiles.json``.

    Returns:
        Dict of character_id -> CharacterProfile.
    """
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            cid: CharacterProfile.model_validate(cp)
            for cid, cp in data.items()
        }
    except (json.JSONDecodeError, ValueError):
        return {}


def save_character_profiles(
    profiles: dict[str, CharacterProfile],
    path: Path,
) -> None:
    """Persist character profiles to a JSON file.

    Args:
        profiles: Character profiles to save.
        path: Output path (e.g. ``out/<book_id>/character_profiles.json``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serialised = {
        cid: p.model_dump(mode="json") for cid, p in sorted(profiles.items())
    }
    path.write_text(
        json.dumps(serialised, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
