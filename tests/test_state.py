"""Story state persistence and voice immutability tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from audiobook_ai.models.character import Character
from audiobook_ai.models.llm import StoryUpdates
from audiobook_ai.models.story import StoryState
from audiobook_ai.models.voice import VoiceProfile
from audiobook_ai.state.store import load_story_state, save_story_state
from audiobook_ai.state.voices import apply_story_updates, ensure_voice, resolve_character_id
from audiobook_ai.voice.errors import VoiceGenerationError
from audiobook_ai.voice.registry import VoiceRegistry


def test_load_save_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "story.json"
    state = StoryState(
        characters=[Character(id="hero", name="Hero", aliases=["H"])],
        voice_map={"hero": "hero"},
    )
    save_story_state(state, path)
    loaded = load_story_state(path)
    assert loaded.characters[0].id == "hero"
    assert loaded.voice_map["hero"] == "hero"


def test_missing_story_returns_empty(tmp_path: Path) -> None:
    state = load_story_state(tmp_path / "missing.json")
    assert state.characters == []
    assert state.voice_map == {}


def test_voice_immutable_after_first_assignment(tmp_path: Path) -> None:
    state = StoryState(characters=[Character(id="hero", name="Hero")])
    cache = tmp_path / "cache"
    book_id = "c" * 32
    first = ensure_voice(
        state, "hero", book_id=book_id, cache_root=cache, generator_name="bank"
    )
    second = ensure_voice(
        state, "hero", book_id=book_id, cache_root=cache, generator_name="bank"
    )
    assert first == second
    assert state.voice_map["hero"] == first
    assert first == "hero"


def test_alias_resolves_same_id(tmp_path: Path) -> None:
    state = StoryState(
        characters=[Character(id="hero", name="Arthur", aliases=[])],
    )
    apply_story_updates(
        state,
        StoryUpdates(aliases={"hero": ["King Arthur"]}),
    )
    resolved = resolve_character_id(state, speaker_name="King Arthur")
    assert resolved == "hero"
    cache = tmp_path / "cache"
    book_id = "d" * 32
    assert ensure_voice(
        state, resolved, book_id=book_id, cache_root=cache, generator_name="bank"
    ) == ensure_voice(
        state, "hero", book_id=book_id, cache_root=cache, generator_name="bank"
    )


def test_apply_story_updates_keeps_voice_profile() -> None:
    state = StoryState()
    apply_story_updates(
        state,
        StoryUpdates(
            characters=[
                Character(
                    id="maria",
                    name="Maria",
                    voice_profile=VoiceProfile(gender="female"),
                )
            ]
        ),
    )
    assert state.characters[0].voice_profile is not None
    assert state.characters[0].voice_profile.gender == "female"


def test_generation_failure_does_not_pollute_voice_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = StoryState(characters=[Character(id="hero", name="Hero")])
    cache = tmp_path / "cache"
    book_id = "e" * 32

    class _Boom:
        def generate_voice(self, *_args, **_kwargs):
            raise VoiceGenerationError("hero", "catalog empty")

        def unload(self) -> None:
            return

    monkeypatch.setattr(
        "audiobook_ai.state.voices.get_voice_generator",
        lambda *args, **kwargs: _Boom(),
    )
    with pytest.raises(VoiceGenerationError):
        ensure_voice(state, "hero", book_id=book_id, cache_root=cache)
    assert "hero" not in state.voice_map
    assert VoiceRegistry(cache_root=cache).get(book_id, "hero") is None
