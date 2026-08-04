"""Tests for chapter cast helpers (Pass 1)."""

from __future__ import annotations

from audiobook_ai.llm.chapter_cast import (
    cast_to_story_updates,
    merge_cast_discoveries,
    restrict_pass2_story_updates,
    speaker_set_from_cast,
)
from audiobook_ai.models.cast import (
    ChapterCastEntry,
    ChapterParticipation,
    LLMCastDiscoveryResponse,
)
from audiobook_ai.models.character import Character
from audiobook_ai.models.llm import StoryUpdates


def test_speaker_set_excludes_mentioned() -> None:
    entries = [
        ChapterCastEntry(
            id="horikita",
            name="Horikita",
            participation=ChapterParticipation.SPEAKER,
        ),
        ChapterCastEntry(
            id="manabu",
            name="Manabu",
            participation=ChapterParticipation.MENTIONED,
        ),
        ChapterCastEntry(
            id="ike",
            name="Ike",
            participation=ChapterParticipation.POSSIBLE_SPEAKER,
        ),
    ]
    allowed = speaker_set_from_cast(entries)
    assert "horikita" in allowed
    assert "ike" in allowed
    assert "manabu" not in allowed
    assert "narrator" in allowed


def test_merge_cast_promotes_participation() -> None:
    a = LLMCastDiscoveryResponse(
        characters=[
            ChapterCastEntry(
                id="girl",
                name="Girl",
                participation=ChapterParticipation.MENTIONED,
                aliases=["the girl"],
            )
        ]
    )
    b = LLMCastDiscoveryResponse(
        characters=[
            ChapterCastEntry(
                id="girl",
                name="Horikita",
                participation=ChapterParticipation.SPEAKER,
                aliases=["Horikita"],
            )
        ]
    )
    merged = merge_cast_discoveries([a, b])
    assert len(merged.characters) == 1
    assert merged.characters[0].participation == ChapterParticipation.SPEAKER
    assert "the girl" in merged.characters[0].aliases
    assert "Horikita" in merged.characters[0].aliases


def test_cast_to_story_updates_drops_participation() -> None:
    discovery = LLMCastDiscoveryResponse(
        characters=[
            ChapterCastEntry(
                id="blond_boy",
                name="Garoto Loiro",
                participation=ChapterParticipation.SPEAKER,
            )
        ]
    )
    updates = cast_to_story_updates(discovery)
    assert updates.characters[0].id == "blond_boy"
    assert not hasattr(updates.characters[0], "participation") or not isinstance(
        updates.characters[0], ChapterCastEntry
    )
    assert isinstance(updates.characters[0], Character)


def test_restrict_pass2_story_updates() -> None:
    updates = StoryUpdates(
        characters=[Character(id="new_guy", name="New")],
        aliases={"blond_boy": ["loiro"], "new_guy": ["x"]},
    )
    restricted = restrict_pass2_story_updates(
        updates, known_ids={"blond_boy", "office_lady"}
    )
    assert restricted.characters == []
    assert restricted.aliases == {"blond_boy": ["loiro"]}
