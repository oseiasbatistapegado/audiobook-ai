"""Tests for PDF/plain-text normalization helpers."""

from __future__ import annotations

from audiobook_ai.parser.text_normalize import repair_midword_linebreaks


def test_repair_elite_split_across_lines() -> None:
    raw = "CLASSROOM OF THE ELI\nTE\n– STORY –\n\nKodo Ikusei Senior High School"
    fixed = repair_midword_linebreaks(raw)
    assert "ELITE" in fixed
    assert "ELI\nTE" not in fixed
    assert "Kodo Ikusei Senior High School" in fixed


def test_repair_preserves_paragraph_and_spaced_wraps() -> None:
    raw = "First paragraph.\n\nSecond paragraph with soft\nwrap left alone if spaced.\nschool \nwith facilities"
    fixed = repair_midword_linebreaks(raw)
    assert "\n\n" in fixed
    assert "school \nwith" in fixed
