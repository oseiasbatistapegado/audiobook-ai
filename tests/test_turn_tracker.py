"""Tests for the deterministic turn tracker."""

from __future__ import annotations

import pytest

from audiobook_ai.llm.scene_graph import SceneGraph
from audiobook_ai.llm.turn_tracker import (
    TurnTracker,
    detect_block_transitions,
)
from audiobook_ai.models.cast import (
    Classification,
    EvidenceEntry,
    EvidenceType,
    TurnAttribution,
    UnitClassification,
)


def _make_unit(
    index: int,
    classification: Classification = Classification.NARRATION,
) -> UnitClassification:
    """Create a UnitClassification for testing."""
    return UnitClassification(
        unit_index=index,
        classification=classification,
        is_indirect=False,
    )


# ---------------------------------------------------------------------------
# TurnTracker — rotation rules
# ---------------------------------------------------------------------------


class TestTurnTrackerRotation:
    """Test circular rotation between active speakers."""

    def test_no_active_speakers(self) -> None:
        tracker = TurnTracker()
        units = [
            _make_unit(0, Classification.EXPLICIT_DIALOGUE),
            _make_unit(1, Classification.EXPLICIT_DIALOGUE),
            _make_unit(2, Classification.EXPLICIT_DIALOGUE),
        ]
        result = tracker.track(units, active_speakers=[])
        assert len(result) == 3
        for attr in result:
            assert attr.speaker_id == "narrator"

    def test_single_active_speaker(self) -> None:
        tracker = TurnTracker()
        units = [
            _make_unit(0, Classification.EXPLICIT_DIALOGUE),
            _make_unit(1, Classification.EXPLICIT_DIALOGUE),
            _make_unit(2, Classification.EXPLICIT_DIALOGUE),
        ]
        result = tracker.track(
            units,
            active_speakers=["ayanokoji"],
        )
        assert all(a.speaker_id == "ayanokoji" for a in result)

    def test_two_speakers_alternate(self) -> None:
        tracker = TurnTracker()
        units = [
            _make_unit(0, Classification.EXPLICIT_DIALOGUE),
            _make_unit(1, Classification.EXPLICIT_DIALOGUE),
            _make_unit(2, Classification.EXPLICIT_DIALOGUE),
            _make_unit(3, Classification.EXPLICIT_DIALOGUE),
            _make_unit(4, Classification.EXPLICIT_DIALOGUE),
            _make_unit(5, Classification.EXPLICIT_DIALOGUE),
        ]
        result = tracker.track(
            units,
            active_speakers=["ayanokoji", "office-lady"],
        )
        # Dialogue units should have non-narrator speakers.
        assert all(a.speaker_id != "narrator" for a in result)

    def test_rotation_with_narration_units(self) -> None:
        """Non-dialogue units should get narrator attribution."""
        tracker = TurnTracker()
        units = [
            _make_unit(0, Classification.NARRATION),
            _make_unit(1, Classification.EXPLICIT_DIALOGUE),
            _make_unit(2, Classification.NARRATION),
            _make_unit(3, Classification.EXPLICIT_DIALOGUE),
        ]
        result = tracker.track(
            units,
            active_speakers=["ayanokoji", "office-lady"],
        )
        # Narration units → narrator
        assert result[0].speaker_id == "narrator"
        assert result[2].speaker_id == "narrator"
        # Dialogue units → speakers from active list.
        assert result[1].speaker_id != "narrator"
        assert result[3].speaker_id != "narrator"


class TestTurnTrackerFocusEntity:
    """Test focus entity as anchor for new blocks."""

    def test_focus_entity_first_turn(self) -> None:
        tracker = TurnTracker(focus_entity="ayanokoji")
        units = [
            _make_unit(0, Classification.EXPLICIT_DIALOGUE),
            _make_unit(1, Classification.EXPLICIT_DIALOGUE),
            _make_unit(2, Classification.EXPLICIT_DIALOGUE),
        ]
        result = tracker.track(
            units,
            active_speakers=["ayanokoji", "office-lady"],
            focus_entity="ayanokoji",
        )
        # First dialogue unit should be from focus entity (or rotation).
        assert any(a.speaker_id == "ayanokoji" for a in result)


class TestTurnTrackerEvidence:
    """Test that TurnAttribution includes proper evidence entries."""

    def test_evidence_type_is_turn_tracker(self) -> None:
        tracker = TurnTracker()
        units = [_make_unit(0, Classification.EXPLICIT_DIALOGUE)]
        result = tracker.track(
            units,
            active_speakers=["ayanokoji"],
        )
        assert result[0].evidence[0].type == EvidenceType.TURN_TRACKER

    def test_confidence_for_single_speaker(self) -> None:
        tracker = TurnTracker()
        units = [_make_unit(0, Classification.EXPLICIT_DIALOGUE)]
        result = tracker.track(
            units,
            active_speakers=["ayanokoji"],
        )
        assert result[0].confidence == 1.0

    def test_confidence_for_rotation(self) -> None:
        tracker = TurnTracker()
        units = [_make_unit(0, Classification.EXPLICIT_DIALOGUE)]
        result = tracker.track(
            units,
            active_speakers=["ayanokoji", "office-lady"],
        )
        assert result[0].confidence == 0.8


class TestDetectBlockTransitions:
    """Test block transition detection."""

    def test_no_edges_no_transitions(self) -> None:
        units = [
            _make_unit(0, Classification.EXPLICIT_DIALOGUE),
            _make_unit(1, Classification.EXPLICIT_DIALOGUE),
        ]
        result = detect_block_transitions(units, graph=None)
        assert result == []

    def test_with_edges_returns_first_dialogue(self) -> None:
        units = [
            _make_unit(0, Classification.EXPLICIT_DIALOGUE),
            _make_unit(1, Classification.EXPLICIT_DIALOGUE),
        ]
        graph = SceneGraph(
            scene_id="test-001",
            focus_entity="ayanokoji",
        )
        result = detect_block_transitions(units, graph=graph)
        # First dialogue unit is always a block start.
        assert 0 in result

    def test_empty_units(self) -> None:
        result = detect_block_transitions([], graph=None)
        assert result == []


class TestTurnAttribution:
    """Test TurnAttribution model validation."""

    def test_turn_attribution_valid(self) -> None:
        attr = TurnAttribution(
            unit_index=0,
            speaker_id="ayanokoji",
            confidence=0.9,
            evidence=[
                EvidenceEntry(
                    type=EvidenceType.TURN_TRACKER,
                    detail="rotation",
                )
            ],
        )
        assert attr.unit_index == 0
        assert attr.speaker_id == "ayanokoji"
        assert attr.confidence == 0.9

    def test_turn_attribution_minimal(self) -> None:
        attr = TurnAttribution(
            unit_index=5,
            speaker_id="narrator",
            confidence=0.5,
        )
        assert attr.evidence == []
