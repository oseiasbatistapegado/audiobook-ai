"""Closed emotion vocabulary for dialogue / TTS."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class Emotion(StrEnum):
    """Standardized emotions accepted by LLM and TTS."""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    FEAR = "fear"
    EXCITED = "excited"
    WHISPER = "whisper"


# Common LLM paraphrases → closed enum (emotion is metadata; Base TTS ignores instruct).
_EMOTION_ALIASES: dict[str, Emotion] = {
    "calm": Emotion.NEUTRAL,
    "serious": Emotion.NEUTRAL,
    "determined": Emotion.NEUTRAL,
    "confused": Emotion.NEUTRAL,
    "curious": Emotion.EXCITED,
    "interested": Emotion.EXCITED,
    "amused": Emotion.HAPPY,
    "joyful": Emotion.HAPPY,
    "grateful": Emotion.HAPPY,
    "proud": Emotion.HAPPY,
    "cheerful": Emotion.HAPPY,
    "melancholy": Emotion.SAD,
    "guilty": Emotion.SAD,
    "apologetic": Emotion.SAD,
    "disappointed": Emotion.SAD,
    "lonely": Emotion.SAD,
    "annoyed": Emotion.ANGRY,
    "furious": Emotion.ANGRY,
    "arrogant": Emotion.ANGRY,
    "contemptuous": Emotion.ANGRY,
    "hostile": Emotion.ANGRY,
    "worried": Emotion.FEAR,
    "concerned": Emotion.FEAR,
    "anxious": Emotion.FEAR,
    "nervous": Emotion.FEAR,
    "scared": Emotion.FEAR,
    "surprised": Emotion.EXCITED,
    "eager": Emotion.EXCITED,
    "quiet": Emotion.WHISPER,
    "soft": Emotion.WHISPER,
    "hushed": Emotion.WHISPER,
}


def coerce_emotion(value: Any) -> Emotion:
    """Map free-form emotion labels onto the closed Emotion enum.

    Unknown values fall back to ``neutral`` so a paraphrasing LLM cannot abort
    the chapter interpret step. Exact enum values are preserved.
    """
    if isinstance(value, Emotion):
        return value
    if value is None:
        return Emotion.NEUTRAL
    raw = str(value).strip().casefold()
    if not raw:
        return Emotion.NEUTRAL
    try:
        return Emotion(raw)
    except ValueError:
        pass
    aliased = _EMOTION_ALIASES.get(raw)
    if aliased is not None:
        return aliased
    return Emotion.NEUTRAL
