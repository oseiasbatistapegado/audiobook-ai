"""End-to-end tests for the hybrid attribution pipeline.

Tests the full hybrid flow: Unit Classifier -> Turn Tracker -> Attribution
with a simulated scene containing 2 characters and ~20 units.
"""

from __future__ import annotations

from audiobook_ai import config
from audiobook_ai.llm.unit_classifier import classify_units
from audiobook_ai.llm.turn_tracker import TurnTracker
from audiobook_ai.llm.speaker_qa import check_speaker_diarization_scene, QASeverity
from audiobook_ai.models.cast import (
    Classification,
    DialogueAttribution,
    TurnAttribution,
    UnitClassification,
)
from audiobook_ai.models.scene import Scene


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# A scene from a Japanese novel (portuguese translation), inspired by
# the "Classroom of the Elite" chapter 5 (paste_1.txt): two characters
# (young-man / office-lady) in dialogue.
SAMPLE_UNITS = [
    "Ele sorriu amplamente e cruzou as pernas.",  # narration
    "Voce esta atrasado.",  # narration (no quotes)
    "Eu me perguntei se ele estava bravo.",  # explicit (1a pessoa)
    "Ele disse que nao ia mais.",  # indirect
    "Sou um jovem saudavel e nao teria inconveniencia.",  # explicit (1a pessoa)
    "A mulher sorriu de canto.",  # narration
    "Ha! Que raciocinio rapido.",  # explicit (? ending)
    "Ele a encarou com curiosidade.",  # narration
    "Por que eu ia ceder o assento?",  # explicit (1a pessoa)
    "A jovem olhou para ele com desconfianca.",  # narration
    "Nao se preocupe.",  # narration (no dash/quotes)
    "Ele assentiu lentamente.",  # narration
    "Por que eu ia desconfiar?",  # explicit (1a pessoa)
    "A mulher esticou as pernas.",  # narration
    "Voce e interessante.",  # narration (no quotes)
    "Ele sorriu sem responder.",  # narration
    "Sou um estudante e nao tenho tempo para isso.",  # explicit (1a pessoa)
    "Ela o observou em silencio.",  # narration
    "Por que eu ia embora?",  # explicit (1a pessoa)
    "O elevador comecou a subir.",  # narration
]

SAMPLE_SCENE = Scene(
    scene_id="scene-001",
    units=list(SAMPLE_UNITS),
    text="\n\n".join(SAMPLE_UNITS),
)

CHARACTER_IDS = ["young-man", "office-lady"]


# ---------------------------------------------------------------------------
# Unit Classifier tests
# ---------------------------------------------------------------------------

class TestUnitClassification:
    """Verify that classify_units correctly classifies all 20 sample units."""

    def test_classifies_all_units(self) -> None:
        results = classify_units(SAMPLE_UNITS)
        assert len(results) == len(SAMPLE_UNITS)

    def test_narration_count(self) -> None:
        results = classify_units(SAMPLE_UNITS)
        narration_count = sum(
            1 for r in results
            if r.classification == Classification.NARRATION
        )
        # At least 8 narration units expected.
        assert narration_count >= 8

    def test_explicit_dialogue_count(self) -> None:
        results = classify_units(SAMPLE_UNITS)
        dialogue_count = sum(
            1 for r in results
            if r.classification == Classification.EXPLICIT_DIALOGUE
        )
        # At least 4 explicit dialogue units expected (1a person markers).
        assert dialogue_count >= 4

    def test_indirect_dialogue_count(self) -> None:
        results = classify_units(SAMPLE_UNITS)
        indirect_count = sum(
            1 for r in results
            if r.classification == Classification.INDIRECT_DIALOGUE
        )
        assert indirect_count >= 1

    def test_classified_indices_are_correct(self) -> None:
        results = classify_units(SAMPLE_UNITS)
        for i, result in enumerate(results):
            assert result.unit_index == i


# ---------------------------------------------------------------------------
# Turn Tracker tests (integrated with classifications)
# ---------------------------------------------------------------------------

class TestTurnTrackerIntegrated:
    """Test Turn Tracker with real classified units."""

    def test_dialogue_units_get_speakers(self) -> None:
        classifications = classify_units(SAMPLE_UNITS)
        tracker = TurnTracker()
        attributions = tracker.track(
            classifications,
            active_speakers=CHARACTER_IDS,
        )
        # All units should have TurnAttribution.
        assert len(attributions) == len(SAMPLE_UNITS)
        # Dialogue units should not be narrator.
        for i, cls in enumerate(classifications):
            if cls.classification.value == "explicit_dialogue":
                assert attributions[i].speaker_id != "narrator"

    def test_narration_units_get_narrator(self) -> None:
        classifications = classify_units(SAMPLE_UNITS)
        tracker = TurnTracker()
        attributions = tracker.track(
            classifications,
            active_speakers=CHARACTER_IDS,
        )
        for i, cls in enumerate(classifications):
            if cls.classification.value == "narration":
                assert attributions[i].speaker_id == "narrator"

    def test_alternation_pattern(self) -> None:
        """Two speakers should alternate in dialogue units."""
        classifications = classify_units(SAMPLE_UNITS)
        tracker = TurnTracker()
        attributions = tracker.track(
            classifications,
            active_speakers=CHARACTER_IDS,
        )
        # Extract speakers for dialogue units only.
        dialogue_speakers = [
            attributions[i].speaker_id
            for i, cls in enumerate(classifications)
            if cls.classification.value in (
                "explicit_dialogue",
                "ambiguous",
            )
        ]
        # Should have 2+ distinct speakers.
        assert len(set(dialogue_speakers)) >= 2

    def test_no_active_speakers_returns_narrator(self) -> None:
        classifications = classify_units(SAMPLE_UNITS)
        tracker = TurnTracker()
        attributions = tracker.track(
            classifications,
            active_speakers=[],
        )
        for attr in attributions:
            assert attr.speaker_id == "narrator"


# ---------------------------------------------------------------------------
# Attribution tests (with resolved units)
# ---------------------------------------------------------------------------

class TestHybridAttribution:
    """Test attribution_scene with pre-resolved Turn Attribution units."""

    def test_attribution_with_resolved_units(self) -> None:
        """Non-ambiguous units should be preserved without LLM."""
        from audiobook_ai.llm.attribution import attribution_scene
        from audiobook_ai.llm.units import InterpretUnit

        units = [
            InterpretUnit(index=i, text=t)
            for i, t in enumerate(SAMPLE_UNITS)
        ]
        classifications = classify_units(SAMPLE_UNITS)
        tracker = TurnTracker()
        turn_attributions = tracker.track(
            classifications,
            active_speakers=CHARACTER_IDS,
        )

        # Build resolved map (non-narrator turn attributions).
        resolved = [
            ta for ta in turn_attributions
            if ta.speaker_id != "narrator"
        ]

        attributions = attribution_scene(
            units,
            candidates=[],
            scene=SAMPLE_SCENE,
            character_profiles={},
            unit_classifications=classifications,
            resolved_units=resolved,
            _chat_fn=lambda msgs: "",
        )

        # Should have one attribution per unit.
        assert len(attributions) == len(units)


# ---------------------------------------------------------------------------
# Scene-level QA tests
# ---------------------------------------------------------------------------

class TestSceneQA:
    """Test scene-level speaker QA."""

    def test_no_narrator_collapse(self) -> None:
        """Diverse speakers -> no collapse detected."""
        attributions = [
            DialogueAttribution(primary="young-man"),
            DialogueAttribution(primary="office-lady"),
            DialogueAttribution(primary="young-man"),
            DialogueAttribution(primary="office-lady"),
        ]
        severity = check_speaker_diarization_scene(
            attributions,
            active_speakers=CHARACTER_IDS,
        )
        assert severity == QASeverity.SKIP

    def test_narrator_collapse_detected(self) -> None:
        """All dialogue units assigned to narrator -> collapse."""
        attributions = [
            DialogueAttribution(primary="narrator"),
            DialogueAttribution(primary="narrator"),
            DialogueAttribution(primary="narrator"),
            DialogueAttribution(primary="narrator"),
        ]
        severity = check_speaker_diarization_scene(
            attributions,
            active_speakers=CHARACTER_IDS,
        )
        assert severity == QASeverity.RIGOROUS

    def test_alternation_fail(self) -> None:
        """2 active speakers but only 1 used -> moderate severity."""
        attributions = [
            DialogueAttribution(primary="young-man"),
            DialogueAttribution(primary="young-man"),
            DialogueAttribution(primary="young-man"),
            DialogueAttribution(primary="young-man"),
        ]
        severity = check_speaker_diarization_scene(
            attributions,
            active_speakers=CHARACTER_IDS,
        )
        assert severity == QASeverity.MODERATE

    def test_closed_set_violation(self) -> None:
        """Speaker not in allowed set -> rigorous."""
        attributions = [
            DialogueAttribution(primary="young-man"),
            DialogueAttribution(primary="unknown-suspect"),
        ]
        severity = check_speaker_diarization_scene(
            attributions,
            active_speakers=CHARACTER_IDS,
            allowed_ids=["young-man", "office-lady", "narrator"],
        )
        assert severity == QASeverity.RIGOROUS

    def test_empty_attributions_skips(self) -> None:
        """Empty attribution list -> skip."""
        severity = check_speaker_diarization_scene([], active_speakers=[])
        assert severity == QASeverity.SKIP


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------

class TestConfigFlags:
    """Verify hybrid attribution configuration constants."""

    def test_hybrid_enabled(self) -> None:
        assert config.HYBRID_ATTRIBUTION_ENABLED is True

    def test_unit_classifier_version(self) -> None:
        assert config.UNIT_CLASSIFIER_VERSION == "v1"

    def test_turn_tracker_version(self) -> None:
        assert config.TURN_TRACKER_VERSION == "v1"

    def test_attribution_policy_v2(self) -> None:
        assert config.ATTRIBUTION_POLICY_VERSION == "v2"

    def test_candidate_generator_version_has_fp(self) -> None:
        assert "fp" in config.CANDIDATE_GENERATOR_VERSION
