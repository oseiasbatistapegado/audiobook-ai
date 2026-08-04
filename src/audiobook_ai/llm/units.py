"""Split long chapters into LLM interpretation units and aggregate results."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from audiobook_ai import config
from audiobook_ai.models.character import Character
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.llm import LLMChapterResponse, StoryUpdates

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class InterpretUnit:
    """One ordered slice of a chapter sent to the LLM."""

    index: int
    text: str

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


def split_chapter_text(
    text: str,
    *,
    max_chars: int | None = None,
) -> list[InterpretUnit]:
    """Split ``text`` into ordered units preferably ≤ ``max_chars``."""
    limit = config.LLM_INTERPRET_MAX_CHARS if max_chars is None else max_chars
    stripped = text.strip()
    if not stripped:
        return [InterpretUnit(index=0, text=text)]
    if len(stripped) <= limit:
        return [InterpretUnit(index=0, text=stripped)]

    pieces = _split_preferring_boundaries(stripped, limit)
    return [InterpretUnit(index=i, text=piece) for i, piece in enumerate(pieces)]


def aggregate_unit_responses(
    responses: list[LLMChapterResponse],
) -> LLMChapterResponse:
    """Concatenate dialogues in order and merge story_updates deterministically."""
    if not responses:
        raise ValueError("aggregate_unit_responses requires at least one response")

    dialogues: list[Dialogue] = []
    for response in responses:
        dialogues.extend(response.dialogues)

    characters_by_id: dict[str, Character] = {}
    aliases: dict[str, list[str]] = {}
    for response in responses:
        updates = response.story_updates
        for character in updates.characters:
            existing = characters_by_id.get(character.id)
            if existing is None:
                characters_by_id[character.id] = character.model_copy(deep=True)
                continue
            merged = existing.model_copy(deep=True)
            merged.aliases = list(
                dict.fromkeys([*merged.aliases, *character.aliases])
            )
            # Last voice_profile for the id wins.
            if character.voice_profile is not None:
                merged.voice_profile = character.voice_profile
            if character.name.strip():
                merged.name = character.name
            characters_by_id[character.id] = merged
        for character_id, new_aliases in updates.aliases.items():
            aliases[character_id] = list(
                dict.fromkeys([*aliases.get(character_id, []), *new_aliases])
            )

    return LLMChapterResponse(
        dialogues=dialogues,
        story_updates=StoryUpdates(
            characters=list(characters_by_id.values()),
            aliases=aliases,
        ),
    )


def _split_preferring_boundaries(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
    if len(paragraphs) > 1:
        packed = _pack_units(paragraphs, limit)
        if len(packed) > 1 or len(packed[0]) <= limit:
            return packed

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if len(sentences) > 1:
        return _pack_units(sentences, limit)

    return _hard_split(text, limit)


def _pack_units(units: list[str], limit: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for unit in units:
        if len(unit) > limit:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(_split_preferring_boundaries(unit, limit))
            continue
        candidate = f"{buf}\n\n{unit}".strip() if buf else unit
        if len(candidate) <= limit:
            buf = candidate
        else:
            if buf:
                out.append(buf)
            buf = unit
    if buf:
        out.append(buf)
    return out


def _hard_split(text: str, limit: int) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)]
