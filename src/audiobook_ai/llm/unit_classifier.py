"""Deterministic unit classifier for hybrid speaker attribution.

Classifies each interpret unit into one of four classes using regex
heuristics (100% code, no LLM):

  1. ``explicit_dialogue`` — quotes (""), dash (—), explicit speech
     verbs, first-person markers (eu, meu, sou, por que eu), or
     short text ending in ?/!
  2. ``indirect_dialogue`` — reported speech ("Ele disse que...")
  3. ``narration`` — pure prose, 3rd person, scene description
  4. ``ambiguous`` — doesn't match any above pattern; may be dialogue
     but needs LLM disambiguation

Returns ``UnitClassification`` per unit.
"""

from __future__ import annotations

import re

from audiobook_ai.models.cast import Classification, UnitClassification

# ---------------------------------------------------------------------------
# Compiled patterns (ordered by priority)
# ---------------------------------------------------------------------------

# Quote characters (various languages).
_QUOTE_CHARS = frozenset(
    [
        '"',  # double quote
        "'",  # single quote
        '«', '»',
        '「', '」', '『', '』',
        '"', '"', '"', '"', '"',
    ]
)

# Dash prefix (dialogue starting with — or –).
_DASH_PREFIX = ("—", "–", "－")

# Speech verbs (Portuguese + English) — explicit attribution markers.
_SPEECH_VERB_RE = re.compile(
    r"\b(?:disse|respondeu|perguntou|falou|gritou|sussurrou|retrucou|"
    r"exclamou|murmurou|acrescentou|insistiu|rebateu|"
    r"said|asked|replied|answered|shouted|whispered)\b",
    re.IGNORECASE,
)

# First-person pronoun markers (PT-BR).
_FIRST_PERSON_RE = re.compile(
    r"\b(?:eu\s+me|eu\s+meu|eu\s+minha|por\s+que\s+eu|"
    r"sou\s+um\b|sou\s+uma\b|"
    r"\bminha\b|\bmeu\b|"
    r"\beu\s+\w+|meu\s+\w+|"
    r"\bmeu\b\s+\w+|"
    r"\bminha\b\s+\w+)\b",
    re.IGNORECASE,
)

# Indirect speech markers.
# Only match patterns where "que" clearly introduces reported speech,
# not interrogative structures like "O que foi isso?".
_INDIRECT_SPEECH_RE = re.compile(
    r"\b(?:disse\s+que|que\s+ia|que\s+não|"
    r"que\s+iria|disse\s+que\s+não)\b",
    re.IGNORECASE,
)

# Short text ending with ? or ! (heuristic for dialogue).
_QUESTION_EXCLAMATION_RE = re.compile(
    r"^[^\n]{1,160}[\?!]\s*$", re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_unit(unit_text: str) -> UnitClassification:
    """Classify one interpret unit into 4 classes.

    Priority order:
      1. Quotes (") → explicit_dialogue
      2. Dash prefix (—) → explicit_dialogue
      3. Short text ending in ?/! (160 chars) → explicit_dialogue
      4. Indirect speech (disse que, que ia, que não) → indirect_dialogue
      5. Speech verb (disse, perguntou) → explicit_dialogue
      6. First-person marker (eu, meu, sou) → explicit_dialogue
      7. Dialogue hints (has ?/! but no other pattern) → ambiguous
      8. Default → narration

    Args:
        unit_text: The text unit to classify.

    Returns:
        A ``UnitClassification`` with the determined class.
    """
    if not unit_text:
        return UnitClassification(
            unit_index=0,
            classification=Classification.NARRATION,
            is_indirect=False,
        )

    # Pattern 1: Quotes (any language).
    if _has_quotes(unit_text):
        return UnitClassification(
            unit_index=0,
            classification=Classification.EXPLICIT_DIALOGUE,
            is_indirect=False,
        )

    # Pattern 2: Dash at start.
    if _starts_with_dash(unit_text):
        return UnitClassification(
            unit_index=0,
            classification=Classification.EXPLICIT_DIALOGUE,
            is_indirect=False,
        )

    # Pattern 3: Short text ending with ? or ! (heuristic for dialogue).
    # Must be checked BEFORE indirect speech, because questions like
    # "O que foi isso?" match "que\s+foi" but should be explicit.
    if _QUESTION_EXCLAMATION_RE.match(unit_text):
        return UnitClassification(
            unit_index=0,
            classification=Classification.EXPLICIT_DIALOGUE,
            is_indirect=False,
        )

    # Pattern 4: Indirect speech.
    if _INDIRECT_SPEECH_RE.search(unit_text):
        return UnitClassification(
            unit_index=0,
            classification=Classification.INDIRECT_DIALOGUE,
            is_indirect=True,
        )

    # Pattern 5: Speech verb.
    if _SPEECH_VERB_RE.search(unit_text):
        return UnitClassification(
            unit_index=0,
            classification=Classification.EXPLICIT_DIALOGUE,
            is_indirect=False,
        )

    # Pattern 6: First-person marker.
    if _FIRST_PERSON_RE.search(unit_text):
        return UnitClassification(
            unit_index=0,
            classification=Classification.EXPLICIT_DIALOGUE,
            is_indirect=False,
        )

    # Pattern 7: Default — narration.
    # But if text contains any dialogue hints (question/exclamation), mark
    # as ambiguous instead of plain narration.
    if _has_dialogue_hints(unit_text):
        return UnitClassification(
            unit_index=0,
            classification=Classification.AMBIGUOUS,
            is_indirect=False,
        )

    return UnitClassification(
        unit_index=0,
        classification=Classification.NARRATION,
        is_indirect=False,
    )


def classify_units(units: list[str]) -> list[UnitClassification]:
    """Classify multiple units with proper indices.

    Args:
        units: List of text units to classify.

    Returns:
        List of ``UnitClassification`` with correct ``unit_index``.
    """
    results: list[UnitClassification] = []
    for idx, unit_text in enumerate(units):
        result = classify_unit(unit_text)
        results.append(
            UnitClassification(
                unit_index=idx,
                classification=result.classification,
                is_indirect=result.is_indirect,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_quotes(text: str) -> bool:
    """Return True when text contains any quote character."""
    return any(c in text for c in _QUOTE_CHARS)


def _starts_with_dash(text: str) -> bool:
    """Return True when text starts with a dash character."""
    stripped = text.lstrip()
    return any(stripped.startswith(d) for d in _DASH_PREFIX)


def _has_dialogue_hints(text: str) -> bool:
    """Return True when text has dialogue-like hints but no explicit markers.

    Checks for question marks or exclamation marks anywhere in the text.
    """
    return bool(re.search(r"[?!]", text))
