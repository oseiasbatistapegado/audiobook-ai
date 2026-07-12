"""Tests for VoiceRegistry, BankVoiceGenerator, and deterministic assignment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiobook_ai.models.character import Character
from audiobook_ai.models.story import StoryState
from audiobook_ai.models.voice import CharacterProfile, VoiceProfile
from audiobook_ai.state.voices import ensure_voice
from audiobook_ai.voice.catalog import discover_base_voices
from audiobook_ai.voice.errors import VoiceGenerationError, VoiceLanguageError
from audiobook_ai.voice.generator import BankVoiceGenerator, derive_seed, get_voice_generator
from audiobook_ai.voice.registry import VoiceRegistry


def test_factory_returns_bank_generator() -> None:
    generator = get_voice_generator("bank")
    assert isinstance(generator, BankVoiceGenerator)


def test_bank_generator_does_not_import_fish_speech() -> None:
    import audiobook_ai.voice.generator as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "fish_speech" not in source
    assert "FishSpeech" not in source


def test_discover_bases_extensible_and_excludes_non_pt_br(tmp_path: Path) -> None:
    assets = tmp_path / "voices"
    for name, language in (
        ("base_a", "pt-BR"),
        ("base_b", "pt-BR"),
        ("base_en", "en-US"),
        ("narrator", "pt-BR"),
    ):
        directory = assets / name
        directory.mkdir(parents=True)
        (directory / "reference.wav").write_bytes(b"RIFF")
        (directory / "reference.lab").write_text("olá\n", encoding="utf-8")
        (directory / "metadata.json").write_text(
            json.dumps(
                {
                    "language": language,
                    "role": "narrator" if name == "narrator" else "character",
                    "gender": "male",
                }
            ),
            encoding="utf-8",
        )
    bases = discover_base_voices(assets_root=assets)
    ids = {base.voice_id for base in bases}
    assert ids == {"base_a", "base_b", "narrator"}
    assert "base_en" not in ids


def test_new_character_gets_voice_existing_reuses(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    state = StoryState(
        characters=[
            Character(id="carlos", name="Carlos", voice_profile=VoiceProfile(gender="male")),
            Character(id="maria", name="Maria", voice_profile=VoiceProfile(gender="female")),
        ]
    )
    carlos = ensure_voice(state, "carlos", cache_root=cache)
    maria = ensure_voice(state, "maria", cache_root=cache)
    assert carlos == "carlos"
    assert maria == "maria"
    assert carlos != maria
    again = ensure_voice(state, "carlos", cache_root=cache)
    assert again == carlos

    registry = VoiceRegistry(cache_root=cache)
    stored = registry.get("carlos")
    assert stored is not None
    assert stored.language == "pt-BR"
    assert stored.base_voice_id is not None
    assert stored.base_voice_id.startswith("base_")


def test_narrator_dedicated_outside_character_pool(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    state = StoryState(
        characters=[
            Character(id="narrator", name="Narrator"),
            Character(id="carlos", name="Carlos"),
            Character(id="maria", name="Maria"),
        ]
    )
    narrator = ensure_voice(state, "narrator", cache_root=cache)
    carlos = ensure_voice(state, "carlos", cache_root=cache)
    maria = ensure_voice(state, "maria", cache_root=cache)
    assert narrator == "narrator"
    registry = VoiceRegistry(cache_root=cache)
    narr_meta = registry.get("narrator")
    assert narr_meta is not None
    assert narr_meta.base_voice_id == "narrator"
    carlos_meta = registry.get("carlos")
    maria_meta = registry.get("maria")
    assert carlos_meta is not None and maria_meta is not None
    assert carlos_meta.base_voice_id != "narrator"
    assert maria_meta.base_voice_id != "narrator"


def test_persisted_wins_over_reselection(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    registry = VoiceRegistry(cache_root=cache)
    state = StoryState(characters=[Character(id="hero", name="Hero")])
    first = ensure_voice(state, "hero", cache_root=cache, registry=registry)
    first_base = registry.get("hero")
    assert first_base is not None

    # Simulate algorithm change by calling generator directly — registry must win.
    generator = BankVoiceGenerator(registry=registry)
    regenerated = generator.generate_voice(CharacterProfile(character_id="hero"))
    assert regenerated.base_voice_id == first_base.base_voice_id
    assert regenerated.reference_wav == first_base.reference_wav
    assert ensure_voice(state, "hero", cache_root=cache, registry=registry) == first


def test_cache_survives_restart(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    state = StoryState(characters=[Character(id="hero", name="Hero")])
    ensure_voice(state, "hero", cache_root=cache)
    # New registry instance / "restart"
    registry = VoiceRegistry(cache_root=cache)
    voice = registry.get("hero")
    assert voice is not None
    assert voice.language == "pt-BR"
    assert (cache / "voices" / "hero" / "reference.wav").is_file()
    assert (cache / "voices" / "hero" / "metadata.json").is_file()


def test_seed_deterministic() -> None:
    profile = VoiceProfile(gender="female", age_range="adult", personality=["warm", "calm"])
    a = derive_seed("maria", profile)
    b = derive_seed("maria", profile)
    c = derive_seed("carlos", profile)
    assert a == b
    assert a != c


def test_reject_non_pt_br_materialization(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    registry = VoiceRegistry(cache_root=cache)
    wav = tmp_path / "reference.wav"
    lab = tmp_path / "reference.lab"
    wav.write_bytes(b"RIFF")
    lab.write_text("hello\n", encoding="utf-8")
    from audiobook_ai.models.voice import GeneratedVoice

    bad = GeneratedVoice(
        voice_id="hero",
        language="pt-PT",
        reference_wav=wav,
        reference_text=lab,
        generator="bank",
        seed=1,
        base_voice_id="base_male_adult",
    )
    with pytest.raises(VoiceLanguageError):
        registry.ensure(bad, character_id="hero")
    assert registry.get("hero") is None


def test_reuse_after_pool_exhaustion(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    # Assign more characters than packaged bases; must still succeed deterministically.
    bases = [
        base
        for base in discover_base_voices()
        if not base.is_narrator
    ]
    assert len(bases) >= 1
    state = StoryState(
        characters=[
            Character(id=f"char-{index}", name=f"Char {index}")
            for index in range(len(bases) + 2)
        ]
    )
    assigned: list[str] = []
    for character in state.characters:
        voice_id = ensure_voice(state, character.id, cache_root=cache)
        assigned.append(voice_id)
        assert voice_id == character.id

    registry = VoiceRegistry(cache_root=cache)
    base_ids = [
        registry.get(character.id).base_voice_id  # type: ignore[union-attr]
        for character in state.characters
    ]
    assert None not in base_ids
    # At least one reused base when pool is smaller than character count.
    assert len(base_ids) > len(set(base_ids))

    # Deterministic across fresh state with same order.
    state2 = StoryState(
        characters=[
            Character(id=f"char-{index}", name=f"Char {index}")
            for index in range(len(bases) + 2)
        ]
    )
    cache2 = tmp_path / "cache2"
    assigned2 = [
        ensure_voice(state2, character.id, cache_root=cache2)
        for character in state2.characters
    ]
    bases2 = [
        VoiceRegistry(cache_root=cache2).get(character.id).base_voice_id  # type: ignore[union-attr]
        for character in state2.characters
    ]
    assert bases2 == base_ids
    assert assigned2 == assigned


def test_empty_catalog_fails_without_voice_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty_assets"
    empty.mkdir()
    monkeypatch.setattr(
        "audiobook_ai.voice.generator.discover_base_voices",
        lambda **_kwargs: [],
    )
    state = StoryState(characters=[Character(id="hero", name="Hero")])
    with pytest.raises(VoiceGenerationError):
        ensure_voice(state, "hero", cache_root=tmp_path / "cache")
    assert "hero" not in state.voice_map
