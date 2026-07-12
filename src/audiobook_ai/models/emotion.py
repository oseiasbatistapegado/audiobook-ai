"""Closed emotion vocabulary for dialogue / TTS."""

from __future__ import annotations

from enum import StrEnum


class Emotion(StrEnum):
    """Standardized emotions accepted by LLM and TTS."""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    FEAR = "fear"
    EXCITED = "excited"
    WHISPER = "whisper"
