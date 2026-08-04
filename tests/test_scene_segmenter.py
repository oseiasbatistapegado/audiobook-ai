"""Unit tests for SceneSegmenter."""

from __future__ import annotations

import json
import pytest

from audiobook_ai.llm.scene_segmenter import SceneSegmenter
from audiobook_ai.models.scene import Scene


def test_segment_basic() -> None:
    text = "Maria disse: olá. João respondeu: bom dia."
    seg = SceneSegmenter()
    scenes = seg.segment(text)
    assert len(scenes) >= 1
    for s in scenes:
        assert isinstance(s, Scene)
        assert isinstance(s.scene_id, str)
        assert isinstance(s.units, list)
        assert isinstance(s.text, str)


def test_segment_deterministic() -> None:
    text = "Maria disse: olá. João respondeu: bom dia. Ela saiu da sala."
    seg = SceneSegmenter()
    first = seg.segment(text)
    second = seg.segment(text)
    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]


def test_segment_short_text() -> None:
    text = "Olá."
    seg = SceneSegmenter()
    scenes = seg.segment(text)
    assert len(scenes) == 1
    assert scenes[0].text == "Olá."


def test_segment_multiple_scenes() -> None:
    text = (
        "Maria entrou na sala e disse: olá.\n\n"
        "João respondeu: bom dia.\n\n"
        "Ela saiu."
    )
    seg = SceneSegmenter()
    scenes = seg.segment(text)
    assert len(scenes) >= 1
    # Each scene should have at least one unit
    for s in scenes:
        assert len(s.units) >= 1
