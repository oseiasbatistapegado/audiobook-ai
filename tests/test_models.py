"""Unit tests for Pydantic model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from audiobook_ai.models.character import Character
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.llm import LLMChapterResponse, StoryUpdates
from audiobook_ai.models.voice import GeneratedVoice, VoiceProfile


def test_valid_minimal_llm_response() -> None:
    payload = {
        "dialogues": [
            {
                "speaker_name": "Narrator",
                "emotion": "neutral",
                "text": "Once upon a time.",
            }
        ],
        "story_updates": {},
    }
    response = LLMChapterResponse.model_validate(payload)
    assert len(response.dialogues) == 1
    assert response.dialogues[0].emotion is Emotion.NEUTRAL


def test_unknown_emotion_falls_back_to_neutral() -> None:
    dialogue = Dialogue.model_validate(
        {
            "speaker_name": "Hero",
            "emotion": "doomsday",
            "text": "No!",
        }
    )
    assert dialogue.emotion is Emotion.NEUTRAL


def test_dialogue_requires_speaker() -> None:
    with pytest.raises(ValidationError):
        Dialogue.model_validate(
            {
                "emotion": "happy",
                "text": "Hello",
            }
        )


def test_angry_dialogue_accepted() -> None:
    dialogue = Dialogue.model_validate(
        {
            "speaker_id": "hero",
            "emotion": "angry",
            "text": "Enough!",
        }
    )
    assert dialogue.emotion is Emotion.ANGRY


def test_character_without_voice_profile() -> None:
    character = Character.model_validate(
        {"id": "carlos", "name": "Carlos", "aliases": []}
    )
    assert character.voice_profile is None


def test_character_with_voice_profile() -> None:
    character = Character.model_validate(
        {
            "id": "maria",
            "name": "Maria",
            "aliases": [],
            "voice_profile": {
                "gender": "female",
                "age_range": "adult",
                "pitch": "medium",
                "personality": ["warm"],
            },
        }
    )
    assert character.voice_profile is not None
    assert character.voice_profile.gender == "female"
    assert character.voice_profile.personality == ["warm"]


def test_story_updates_accepts_optional_voice_profile() -> None:
    updates = StoryUpdates.model_validate(
        {
            "characters": [
                {
                    "id": "hero",
                    "name": "Hero",
                    "voice_profile": {"gender": "male"},
                }
            ]
        }
    )
    assert updates.characters[0].voice_profile is not None
    assert isinstance(updates.characters[0].voice_profile, VoiceProfile)


def test_generated_voice_requires_language_default_pt_br(tmp_path) -> None:
    wav = tmp_path / "reference.wav"
    lab = tmp_path / "reference.lab"
    wav.write_bytes(b"RIFF")
    lab.write_text("olá\n", encoding="utf-8")
    voice = GeneratedVoice(
        voice_id="hero",
        character_id="hero",
        book_id="a" * 32,
        reference_wav=wav,
        reference_text=lab,
        generator="bank",
        generator_version="1",
        model_id="bank:v1",
        seed=42,
        base_voice_id="base_male_adult",
    )
    assert voice.language == "pt-BR"
