"""Tests for the deterministic unit classifier."""

from __future__ import annotations

import pytest

from audiobook_ai.llm.unit_classifier import (
    classify_unit,
    classify_units,
)
from audiobook_ai.models.cast import Classification


class TestClassifyUnit:
    """Tests for classify_unit covering all 4 classes and edge cases."""

    # --- explicit_dialogue: quotes ---
    def test_double_quotes(self) -> None:
        result = classify_unit('"Você está atrasado."')
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    def test_single_quotes(self) -> None:
        result = classify_unit("'Olá, mundo!'")
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    def test_japanese_quotes(self) -> None:
        result = classify_unit('「おはよう」')
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    # --- explicit_dialogue: dash prefix ---
    def test_dash_prefix(self) -> None:
        result = classify_unit("— Você está atrasado.")
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    # --- explicit_dialogue: speech verb ---
    def test_speech_verb_portuguese(self) -> None:
        # "disse que" should be indirect_dialogue (checked before explicit verb)
        result = classify_unit("Ele disse que não ia mais.")
        assert result.classification == Classification.INDIRECT_DIALOGUE
        assert result.is_indirect is True

    def test_speech_verb_explicit(self) -> None:
        result = classify_unit("Horikita disse: Vamos embora.")
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    def test_speech_verb_english(self) -> None:
        result = classify_unit("Ayanokoji said: Leave now.")
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    # --- explicit_dialogue: first person ---
    def test_first_person_eu(self) -> None:
        result = classify_unit("Por que eu ia ceder o assento?")
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    def test_first_person_eu_me(self) -> None:
        result = classify_unit("Eu me perguntei se ele estava bravo")
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    def test_first_person_sou_um(self) -> None:
        result = classify_unit(
            "Sou um jovem saudável e não teria inconveniência"
        )
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    def test_first_person_meu(self) -> None:
        result = classify_unit("Meu deus, que situação.")
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    # --- explicit_dialogue: question/exclamation ---
    def test_exclamation(self) -> None:
        # Text has ! in the middle but doesn't end with ?/!, so short-text
        # regex doesn't match. _has_dialogue_hints finds the !, making it
        # ambiguous.
        result = classify_unit("Hã! Que raciocínio absurdo.")
        assert result.classification == Classification.AMBIGUOUS

    def test_question_short(self) -> None:
        result = classify_unit("O que foi isso?")
        assert result.classification == Classification.EXPLICIT_DIALOGUE

    # --- indirect_dialogue ---
    def test_indirect_disse_que(self) -> None:
        result = classify_unit("Ele disse que não ia mais.")
        assert result.classification == Classification.INDIRECT_DIALOGUE
        assert result.is_indirect is True

    def test_indirect_que_ia(self) -> None:
        result = classify_unit("Ele achou que ia conseguir.")
        assert result.classification == Classification.INDIRECT_DIALOGUE
        assert result.is_indirect is True

    # --- narration ---
    def test_third_person_prose(self) -> None:
        result = classify_unit("Ele sorriu amplamente e cruzou as pernas.")
        assert result.classification == Classification.NARRATION

    def test_scene_description(self) -> None:
        result = classify_unit(
            "A sala estava silenciosa, iluminada pela luz da lua."
        )
        assert result.classification == Classification.NARRATION

    # --- ambiguous ---
    def test_ambiguous_no_markers(self) -> None:
        # Text has no dialogue hints at all → narration (no ?/! present).
        result = classify_unit("O garoto estava sentado na cadeira.")
        assert result.classification == Classification.NARRATION

    def test_ambiguous_dialogue_hints(self) -> None:
        # Text has ! but no explicit markers → ambiguous.
        result = classify_unit("Hã! Que raciocínio absurdo.")
        assert result.classification == Classification.AMBIGUOUS

    def test_ambiguous_empty(self) -> None:
        result = classify_unit("")
        assert result.classification == Classification.NARRATION

    def test_ambiguous_long_text_with_question(self) -> None:
        # Long text with a question mark should be ambiguous (not explicit
        # because it exceeds the 160 char limit for ?/!).
        long_text = (
            "Ele olhou ao redor da sala, ponderando se deveria "
            "revelar a verdade para todos os presentes, mas "
            "decidiu que era melhor manter o segredo por enquanto. "
            "Será que alguém perceberia? Certamente não."
        )
        result = classify_unit(long_text)
        assert result.classification == Classification.AMBIGUOUS


class TestClassifyUnits:
    """Tests for classify_units (batch classification with indices)."""

    def test_classify_units_preserves_indices(self) -> None:
        units = [
            "Ele sorriu amplamente.",
            '"Você está atrasado."',
            "Por que eu ia ceder o assento?",
        ]
        result = classify_units(units)
        assert len(result) == 3
        assert result[0].unit_index == 0
        assert result[1].unit_index == 1
        assert result[2].unit_index == 2

    def test_classify_units_empty(self) -> None:
        result = classify_units([])
        assert result == []

    def test_classify_units_all_dialogue(self) -> None:
        units = [
            '"Primeiro turno."',
            '"Segundo turno."',
        ]
        result = classify_units(units)
        assert all(
            r.classification == Classification.EXPLICIT_DIALOGUE
            for r in result
        )
