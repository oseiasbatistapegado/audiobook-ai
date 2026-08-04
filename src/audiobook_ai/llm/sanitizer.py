"""Segment classification — 3-class categorization of text units.

Classifies each text segment as:
- ``explicit_dialogue`` — quoted dialogue (aspas, travessão, verbos de fala)
- ``indirect_dialogue`` — reported speech ("Ele disse que...", indirect)
- ``narration`` — pure prose

Also provides ``coerce_speaker_from_classification`` for mapping
classification back to speaker attribution.
"""

from __future__ import annotations

import re

from audiobook_ai.models.cast import Classification, SegmentClassification
from audiobook_ai.models.cast import DialogueAttribution as _DialogueAttribution


# Compiled patterns.
_DASH_DIALOGUE = re.compile(r"^\s*[\u2014\u2013]")
_QUOTE_OPEN = re.compile(r'^[\"\'"«»]')
_SPEECH_VERB = re.compile(
    r"(?:disse|respondeu|perguntou|falou|gritou|sussurrou|"
    r"retrucou|exclamou|murmurou|acrescentou|insistiu)"
)
_INDIRECT_MARKER = re.compile(
    r"\b(disse que|disse que\s+ele|respondeu que|perguntou se|"
    r"falou que|acrescentou que|gritou que|sussurrou que|"
    r"ele disse que|ela disse que|disse que\s+a|respondeu que\s+a)\b",
    re.IGNORECASE,
)


def classify_segment(text: str) -> str:
    """Classify a text segment into 3 classes.

    Args:
        text: Text to classify.

    Returns:
        ``"explicit_dialogue"``, ``"indirect_dialogue"``, or ``"narration"``.
    """
    if not text.strip():
        return Classification.NARRATION.value

    # Explicit dialogue markers: dash at start, opening quote.
    if _DASH_DIALOGUE.match(text) or _QUOTE_OPEN.match(text):
        return Classification.EXPLICIT_DIALOGUE.value

    # Speech verb near the text.
    if _SPEECH_VERB.search(text):
        return Classification.EXPLICIT_DIALOGUE.value

    # Indirect dialogue markers.
    if _INDIRECT_MARKER.search(text):
        return Classification.INDIRECT_DIALOGUE.value

    # Default: narration.
    return Classification.NARRATION.value


def classify_segment_obj(text: str) -> SegmentClassification:
    """Classify and return a ``SegmentClassification`` model object."""
    classification = classify_segment(text)
    is_indirect = classification == Classification.INDIRECT_DIALOGUE.value
    return SegmentClassification(
        text=text,
        classification=Classification(classification),
        is_indirect=is_indirect,
    )


def coerce_speaker_from_classification(
    attribution: _DialogueAttribution,
    classification: str,
) -> _DialogueAttribution:
    """Map classification to speaker_id coercion.

    If classification is ``narration`` and the attribution's primary speaker
    is not ``narrator``, coerce to ``narrator``.

    Args:
        attribution: The original attribution.
        classification: The classification string.

    Returns:
        A potentially updated ``DialogueAttribution``.
    """
    if classification == Classification.NARRATION.value:
        # Coerce narration turns to narrator.
        return attribution.model_copy(
            update={"primary": "narrator", "ranked_candidates": ["narrator"]}
        )
    return attribution
