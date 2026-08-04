"""Tests for VoiceRegistry, BankVoiceGenerator, and deterministic assignment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiobook_ai.models.character import Character
from audiobook_ai.models.story import StoryState
from audiobook_ai.models.voice import CharacterProfile, VoiceProfile
from audiobook_ai.state.voices import ensure_voice
from audiobook_ai.voice.catalog import BaseVoice, discover_base_voices
from audiobook_ai.voice.errors import VoiceGenerationError, VoiceLanguageError
from audiobook_ai.voice.generator import BankVoiceGenerator, derive_seed, get_voice_generator
from audiobook_ai.voice.registry import VoiceRegistry


BOOK_ID = "test_book_id_000000000000000000000000"


def _make_base_voice_dir(
    assets_root: Path, name: str, language: str = "pt-BR", role: str = "character"
) -> Path:
    """Create a voice directory with reference files and metadata."""
    directory = assets_root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "reference.wav").write_bytes(b"RIFF....WAVE")
    (directory / "reference.lab").write_text("olá\n", encoding="utf-8")
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "language": language,
                "role": role,
                "gender": "male" if name.startswith("base_m") else "female",
            }
        ),
        encoding="utf-8",
    )
    return directory


def _mock_discover_bases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    assets: list[tuple[str, str, str]],
) -> Path:
    """Create fake voice assets and monkeypatch discover_base_voices.

    Each entry is ``(name, language, role)``.
    Returns the assets root path.
    """
    assets_root = tmp_path / "fake_voices"
    for name, language, role in assets:
        _make_base_voice_dir(assets_root, name, language, role)
    monkeypatch.setattr(
        "audiobook_ai.voice.generator.discover_base_voices",
        lambda **_kw: discover_base_voices(assets_root=assets_root),
    )
    return assets_root


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


def test_new_character_gets_voice_existing_reuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets = _mock_discover_bases(monkeypatch, tmp_path, [
        ("base_male_1", "pt-BR", "character"),
        ("base_female_1", "pt-BR", "character"),
    ])
    cache = tmp_path / "cache"
    state = StoryState(
        characters=[
            Character(id="carlos", name="Carlos", voice_profile=VoiceProfile(gender="male")),
            Character(id="maria", name="Maria", voice_profile=VoiceProfile(gender="female")),
        ]
    )
    carlos = ensure_voice(
        state, "carlos", book_id=BOOK_ID, cache_root=cache, generator_name="bank"
    )
    maria = ensure_voice(
        state, "maria", book_id=BOOK_ID, cache_root=cache, generator_name="bank"
    )
    assert carlos == "carlos"
    assert maria == "maria"
    assert carlos != maria
    again = ensure_voice(
        state, "carlos", book_id=BOOK_ID, cache_root=cache, generator_name="bank"
    )
    assert again == carlos

    registry = VoiceRegistry(cache_root=cache)
    stored = registry.get(BOOK_ID, "carlos")
    assert stored is not None
    assert stored.language == "pt-BR"
    assert stored.base_voice_id is not None
    assert stored.base_voice_id.startswith("base_")


def test_narrator_dedicated_outside_character_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets = _mock_discover_bases(monkeypatch, tmp_path, [
        ("base_male_1", "pt-BR", "character"),
        ("base_female_1", "pt-BR", "character"),
        ("narrator", "pt-BR", "narrator"),
    ])
    cache = tmp_path / "cache"
    state = StoryState(
        characters=[
            Character(id="narrator", name="Narrator"),
            Character(id="carlos", name="Carlos"),
            Character(id="maria", name="Maria"),
        ]
    )
    narrator = ensure_voice(
        state, "narrator", book_id=BOOK_ID, cache_root=cache, generator_name="bank"
    )
    carlos = ensure_voice(
        state, "carlos", book_id=BOOK_ID, cache_root=cache, generator_name="bank"
    )
    maria = ensure_voice(
        state, "maria", book_id=BOOK_ID, cache_root=cache, generator_name="bank"
    )
    assert narrator == "narrator"
    registry = VoiceRegistry(cache_root=cache)
    narr_meta = registry.get(BOOK_ID, "narrator")
    assert narr_meta is not None
    assert narr_meta.base_voice_id == "narrator"
    carlos_meta = registry.get(BOOK_ID, "carlos")
    maria_meta = registry.get(BOOK_ID, "maria")
    assert carlos_meta is not None and maria_meta is not None
    assert carlos_meta.base_voice_id != "narrator"
    assert maria_meta.base_voice_id != "narrator"


def test_persisted_wins_over_reselection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_discover_bases(monkeypatch, tmp_path, [
        ("base_male_1", "pt-BR", "character"),
    ])
    cache = tmp_path / "cache"
    registry = VoiceRegistry(cache_root=cache)
    state = StoryState(characters=[Character(id="hero", name="Hero")])
    first = ensure_voice(
        state, "hero", book_id=BOOK_ID, cache_root=cache, registry=registry, generator_name="bank"
    )
    first_base = registry.get(BOOK_ID, "hero")
    assert first_base is not None

    # Simulate algorithm change by calling generator directly — registry must win.
    generator = BankVoiceGenerator(registry=registry)
    regenerated = generator.generate_voice(
        CharacterProfile(character_id="hero"), book_id=BOOK_ID
    )
    assert regenerated.base_voice_id == first_base.base_voice_id
    assert regenerated.reference_wav == first_base.reference_wav
    assert ensure_voice(
        state, "hero", book_id=BOOK_ID, cache_root=cache, registry=registry, generator_name="bank"
    ) == first


def test_cache_survives_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_discover_bases(monkeypatch, tmp_path, [
        ("base_male_1", "pt-BR", "character"),
    ])
    cache = tmp_path / "cache"
    state = StoryState(characters=[Character(id="hero", name="Hero")])
    ensure_voice(
        state, "hero", book_id=BOOK_ID, cache_root=cache, generator_name="bank"
    )
    # New registry instance / "restart"
    registry = VoiceRegistry(cache_root=cache)
    voice = registry.get(BOOK_ID, "hero")
    assert voice is not None
    assert voice.language == "pt-BR"
    assert (cache / "voices" / BOOK_ID / "hero" / "reference.wav").is_file()
    assert (cache / "voices" / BOOK_ID / "hero" / "metadata.json").is_file()


def test_seed_deterministic() -> None:
    profile = VoiceProfile(gender="female", age_range="adult", personality=["warm", "calm"])
    a = derive_seed(
        book_id=BOOK_ID, character_id="maria", profile=profile, model_id="test", generator_version="1"
    )
    b = derive_seed(
        book_id=BOOK_ID, character_id="maria", profile=profile, model_id="test", generator_version="1"
    )
    c = derive_seed(
        book_id=BOOK_ID, character_id="carlos", profile=profile, model_id="test", generator_version="1"
    )
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
        character_id="hero",
        book_id=BOOK_ID,
        language="pt-PT",
        reference_wav=wav,
        reference_text=lab,
        generator="bank",
        generator_version="1",
        model_id="test",
        seed=1,
    )
    with pytest.raises(VoiceLanguageError):
        registry.ensure(bad)
    assert registry.get(BOOK_ID, "hero") is None


def test_reuse_after_pool_exhaustion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets = _mock_discover_bases(monkeypatch, tmp_path, [
        ("base_male_1", "pt-BR", "character"),
        ("base_male_2", "pt-BR", "character"),
        ("base_female_1", "pt-BR", "character"),
    ])
    cache = tmp_path / "cache"
    # Assign more characters than packaged bases; must still succeed deterministically.
    bases = discover_base_voices(assets_root=assets)
    assert len(bases) >= 1
    state = StoryState(
        characters=[
            Character(id=f"char-{index}", name=f"Char {index}")
            for index in range(len(bases) + 2)
        ]
    )
    assigned: list[str] = []
    for character in state.characters:
        voice_id = ensure_voice(
            state, character.id, book_id=BOOK_ID, cache_root=cache, generator_name="bank"
        )
        assigned.append(voice_id)
        assert voice_id == character.id

    registry = VoiceRegistry(cache_root=cache)
    base_ids = [
        registry.get(BOOK_ID, character.id).base_voice_id  # type: ignore[union-attr]
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
        ensure_voice(state2, character.id, book_id=BOOK_ID, cache_root=cache2, generator_name="bank")
        for character in state2.characters
    ]
    bases2 = [
        VoiceRegistry(cache_root=cache2).get(BOOK_ID, character.id).base_voice_id  # type: ignore[union-attr]
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
        ensure_voice(
            state, "hero", book_id=BOOK_ID, cache_root=tmp_path / "cache", generator_name="bank"
        )
    assert "hero" not in state.voice_map
