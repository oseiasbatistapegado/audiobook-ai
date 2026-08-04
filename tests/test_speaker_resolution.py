"""Unit tests for speaker resolution pipeline components."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from audiobook_ai import config
from audiobook_ai.llm.candidate_generator import _step_first_person, generate_candidates
from audiobook_ai.llm.scene_graph import build_scene_graph
from audiobook_ai.llm.sanitizer import classify_segment
from audiobook_ai.llm.speaker_qa import qa_severity, QASeverity
from audiobook_ai.llm.cache import attribution_cache_key, interpretation_cache_key
from audiobook_ai.models.cast import EvidenceEntry, EvidenceType, CharacterProfile
from audiobook_ai.models.dialogue import Emotion
from audiobook_ai.models.scene import Scene
from audiobook_ai.llm.interpretation_state import InterpretationState


# --- classify_segment ---

class TestClassifySegment:
    def test_explicit_dialogue_with_quotes(self) -> None:
        assert classify_segment("'Olá, como vai?' disse Maria") == "explicit_dialogue"

    def test_explicit_dialogue_with_dash(self) -> None:
        # Portuguese dash-style dialogue
        assert classify_segment("— Olá, como vai? — disse Maria") == "explicit_dialogue"

    def test_narration(self) -> None:
        assert classify_segment("Ela entrou na sala devagar.") == "narration"

    def test_indirect_dialogue(self) -> None:
        assert classify_segment("Ele disse que viria mais tarde.") == "explicit_dialogue"

    def test_prose_first_person(self) -> None:
        assert classify_segment("Eu olhei para o horizonte e pensei.") == "narration"


# --- qa_severity ---

class TestQASeverity:
    def test_explicit_skips(self) -> None:
        assert qa_severity([EvidenceEntry(type=EvidenceType.EXPLICIT, detail="x")]) == QASeverity.SKIP

    def test_turn_order_moderate(self) -> None:
        assert qa_severity([EvidenceEntry(type=EvidenceType.TURN_ORDER, detail="x")]) == QASeverity.MODERATE

    def test_scene_context_moderate(self) -> None:
        assert qa_severity([EvidenceEntry(type=EvidenceType.SCENE_CONTEXT, detail="x")]) == QASeverity.MODERATE

    def test_alias_match_moderate(self) -> None:
        assert qa_severity([EvidenceEntry(type=EvidenceType.ALIAS_MATCH, detail="x")]) == QASeverity.MODERATE

    def test_relationship_moderate(self) -> None:
        assert qa_severity([EvidenceEntry(type=EvidenceType.RELATIONSHIP, detail="x")]) == QASeverity.MODERATE

    def test_embedding_low_gap_rigorous(self) -> None:
        entry = EvidenceEntry(type=EvidenceType.EMBEDDING, detail="embedding_similarity:0.15")
        assert qa_severity([entry]) == QASeverity.RIGOROUS

    def test_embedding_high_gap_moderate(self) -> None:
        entry = EvidenceEntry(type=EvidenceType.EMBEDDING, detail="embedding_similarity:0.80")
        assert qa_severity([entry]) == QASeverity.MODERATE

    def test_empty_evidence_moderate(self) -> None:
        assert qa_severity([]) == QASeverity.MODERATE


# --- build_scene_graph ---

class TestBuildSceneGraph:
    def test_basic_graph(self) -> None:
        units = ["Olá", "Oi"]
        profiles: dict[str, CharacterProfile] = {}
        graph = build_scene_graph(units, profiles, [])
        assert isinstance(graph.scene_id, str)
        assert isinstance(graph.entities, list)

    def test_graph_with_characters(self) -> None:
        profiles = {
            "maria": CharacterProfile(
                id="maria", name="Maria", aliases=["Mari"],
                gender="feminino", role="secondary",
                known_names=["Maria", "Mari"],
            ),
        }
        units = ["Maria entrou na sala."]
        graph = build_scene_graph(units, profiles, [])
        assert len(graph.entities) >= 1


# --- generate_candidates ---

class TestGenerateCandidates:
    def test_explicit_name(self) -> None:
        profiles = {
            "maria": CharacterProfile(
                id="maria", name="Maria Silva", aliases=["Maria"],
                gender="feminino", role="secondary",
                known_names=["Maria"],
            ),
        }
        candidates = generate_candidates("Maria disse: olá", profiles, None)
        assert len(candidates) >= 1
        assert candidates[0].speaker_id == "maria"

    def test_empty_profiles(self) -> None:
        candidates = generate_candidates("Alguém falou.", {}, None)
        # Should not crash; may return empty list
        assert isinstance(candidates, list)


# --- cache keys ---

class TestCacheKeys:
    def test_attribution_key_format(self) -> None:
        scene = Scene(scene_id="s1", units=["test"], text="test")
        key = attribution_cache_key(scene, character_profiles_hash="hp1")
        assert key.startswith("attr-")
        assert len(key) > 10  # SHA-256 hex + prefix

    def test_interpretation_key_format(self) -> None:
        scene = Scene(scene_id="s1", units=["test"], text="test")
        key = interpretation_cache_key(scene, attribution_cache_key="attr-abc123")
        assert key.startswith("interp-")
        assert len(key) > 10

    def test_different_scenes_different_keys(self) -> None:
        scene1 = Scene(scene_id="s1", units=["a"], text="text1")
        scene2 = Scene(scene_id="s2", units=["b"], text="text2")
        key1 = attribution_cache_key(scene1, character_profiles_hash="hp")
        key2 = attribution_cache_key(scene2, character_profiles_hash="hp")
        assert key1 != key2

    def test_policy_version_invalidation(self) -> None:
        scene = Scene(scene_id="s1", units=["a"], text="text")
        key_v1 = attribution_cache_key(scene, character_profiles_hash="hp", attribution_policy_version="v1")
        key_v2 = attribution_cache_key(scene, character_profiles_hash="hp", attribution_policy_version="v2")
        assert key_v1 != key_v2


# --- InterpretationState serialization ---

class TestInterpretationState:
    def test_model_dump_json(self) -> None:
        state = InterpretationState()
        json_str = state.model_dump_json()
        parsed = json.loads(json_str)
        assert "scenes" in parsed
        assert "character_profiles" in parsed
        assert "qa_status" in parsed

    def test_dump_scene_debug(self) -> None:
        state = InterpretationState()
        debug = state.dump_scene_debug("scene-1")
        assert debug["_meta"]["scene_id"] == "scene-1"

    def test_persistence_roundtrip(self) -> None:
        state = InterpretationState()
        with tempfile.TemporaryDirectory() as tmp:
            saved = state.save_scene("s1", Path(tmp))
            loaded = InterpretationState.load_scene(saved)
            assert loaded is not None
            assert loaded.scenes == state.scenes

    def test_debug_dump_disabled_by_default(self) -> None:
        state = InterpretationState()
        with tempfile.TemporaryDirectory() as tmp:
            result = state.write_debug_scene("s1", Path(tmp))
            assert result is None  # DEBUG_STATE_DUMP is False by default


# --- needs_review TTS omission ---

class TestNeedsReviewTTS:
    def test_skipped_in_partition(self) -> None:
        from audiobook_ai.models.dialogue import Dialogue
        from audiobook_ai.models.speech import partition_dialogues

        good = Dialogue(
            speaker_id="maria", text="Olá", emotion=Emotion.NEUTRAL,
        )
        bad = Dialogue(
            speaker_id=None, text="??", emotion=Emotion.NEUTRAL,
            status="needs_review", rejection_reason="QA failed",
        )
        chunks = partition_dialogues(
            [good, bad],
            chapter_id="ch-1",
            resolve_character_id=lambda d: getattr(d, "speaker_id", None),
        )
        assert len(chunks) == 1  # Only the good dialogue produces chunks
        assert chunks[0].text == "Olá"


# --- _step_first_person ---

class TestStepFirstPerson:
    def test_detects_eu_marker(self) -> None:
        result = _step_first_person("Por que eu ia ceder o assento?", [])
        assert len(result) == 1
        assert result[0].speaker_id == "narrator"
        assert result[0].evidence[0].type == EvidenceType.FIRST_PERSON

    def test_detects_eu_me_marker(self) -> None:
        result = _step_first_person("Eu me perguntei se ele estava bravo", [])
        assert len(result) == 1
        assert result[0].speaker_id == "narrator"

    def test_detects_sou_um_marker(self) -> None:
        result = _step_first_person("Sou um jovem saudável", [])
        assert len(result) == 1
        assert result[0].speaker_id == "narrator"

    def test_detects_meu_marker(self) -> None:
        result = _step_first_person("Meu deus, que situação", [])
        assert len(result) == 1
        assert result[0].speaker_id == "narrator"

    def test_no_match_returns_empty(self) -> None:
        result = _step_first_person("Ele sorriu amplamente", [])
        assert result == []

    def test_does_not_assign_character_id(self) -> None:
        """First-person marker signals dialogue but doesn't pick a speaker."""
        result = _step_first_person("Por que eu ia ceder o assento?", [])
        # The speaker is "narrator" as a placeholder — Turn Tracker resolves it.
        assert result[0].speaker_id == "narrator"
