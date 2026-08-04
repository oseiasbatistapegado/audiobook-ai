"""Tests for interpret-unit splitting and aggregation."""

from __future__ import annotations

from audiobook_ai import config
from audiobook_ai.llm.units import aggregate_unit_responses, split_chapter_text
from audiobook_ai.models.character import Character
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.llm import LLMChapterResponse, StoryUpdates


def test_short_chapter_is_single_unit() -> None:
    units = split_chapter_text("Hello world.", max_chars=6000)
    assert len(units) == 1
    assert units[0].index == 0
    assert units[0].text == "Hello world."


def test_long_chapter_splits_on_paragraphs() -> None:
    para = "A" * 2000
    text = f"{para}\n\n{para}\n\n{para}\n\n{para}"
    units = split_chapter_text(text, max_chars=6000)
    assert len(units) >= 2
    assert "".join(u.text.replace("\n\n", "") for u in units).count("A") == 8000
    assert all(len(u.text) <= 6000 or "\n\n" not in u.text for u in units)
    assert [u.index for u in units] == list(range(len(units)))


def test_default_max_chars_is_6000() -> None:
    assert config.LLM_INTERPRET_MAX_CHARS == 6000
    text = ("word " * 2000).strip()  # well over 6000
    # Ensure paragraphs to pack
    chunks = ["Para " + ("x" * 2500) for _ in range(4)]
    text = "\n\n".join(chunks)
    units = split_chapter_text(text)
    assert len(units) >= 2


def test_aggregate_preserves_dialogue_order_and_merges_aliases() -> None:
    r1 = LLMChapterResponse(
        dialogues=[
            Dialogue(speaker_id="narrator", emotion=Emotion.NEUTRAL, text="Um."),
        ],
        story_updates=StoryUpdates(
            characters=[Character(id="sudou", name="Sudou", aliases=["Ken"])],
            aliases={"sudou": ["Ken"]},
        ),
    )
    r2 = LLMChapterResponse(
        dialogues=[
            Dialogue(speaker_id="sudou", emotion=Emotion.HAPPY, text="Dois."),
        ],
        story_updates=StoryUpdates(
            characters=[Character(id="sudou", name="Sudou", aliases=["Sudo"])],
            aliases={"sudou": ["Sudo"]},
        ),
    )
    merged = aggregate_unit_responses([r1, r2])
    assert [d.text for d in merged.dialogues] == ["Um.", "Dois."]
    assert merged.story_updates.aliases["sudou"] == ["Ken", "Sudo"]
    assert set(merged.story_updates.characters[0].aliases) >= {"Ken", "Sudo"}
