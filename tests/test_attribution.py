"""Unit tests for ``attribution_scene`` with explicit attribution and chained dialogue."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiobook_ai.llm.attribution import (
    _read_attribution_cache,
    _write_attribution_cache,
    attribution_scene,
)
from audiobook_ai.llm.units import InterpretUnit
from audiobook_ai.models.cast import (
    Candidate,
    CharacterProfile,
    DialogueAttribution,
    EvidenceEntry,
    EvidenceType,
)
from audiobook_ai.models.scene import Scene


def _fake_chat_success() -> str:
    """Return valid attribution JSON for two units."""
    return json.dumps(
        {
            "attributions": [
                {
                    "primary": "maria",
                    "ranked_candidates": ["maria", "narrator"],
                    "evidence": [
                        {"type": "EXPLICIT", "detail": "Maria (nome próprio explícito no texto)"}
                    ],
                    "reason": "nome próprio explícito",
                },
                {
                    "primary": "joao",
                    "ranked_candidates": ["joao", "narrator"],
                    "evidence": [
                        {"type": "TURN_ORDER", "detail": "João responde após Maria"}
                    ],
                    "reason": "turno sequencial",
                },
            ],
        }
    )


def _fake_chat_fails() -> str:
    """Return invalid JSON."""
    return "not-json-at-all"


def _fake_chat_partial() -> str:
    """Return attribution with only one entry for two units."""
    return json.dumps(
        {
            "attributions": [
                {
                    "primary": "maria",
                    "ranked_candidates": ["maria"],
                    "evidence": [],
                }
            ],
        }
    )


def _fake_chat_invalid_primary() -> str:
    """Return attribution with primary not in allowed set."""
    return json.dumps(
        {
            "attributions": [
                {
                    "primary": "unknown_speaker",
                    "ranked_candidates": [],
                    "evidence": [],
                }
            ],
        }
    )


_PROFILES: dict[str, CharacterProfile] = {
    "maria": CharacterProfile(id="maria", name="Maria", aliases=["Mari"]),
    "joao": CharacterProfile(id="joao", name="João", aliases=["Jo"]),
}


# --- attribution_scene basic ---

class TestAttributionScene:
    def test_explicit_attribution(self) -> None:
        """Attribution resolves explicit speaker names correctly."""
        units = [
            InterpretUnit(index=0, text="'Olá' disse Maria."),
            InterpretUnit(index=1, text="João respondeu: 'Tudo bem?'"),
        ]
        candidates: list[Candidate] = [
            Candidate(speaker_id="maria", score=0.9, evidence=[]),
            Candidate(speaker_id="joao", score=0.7, evidence=[]),
        ]
        scene = Scene(scene_id="scene-001", text="Maria e João conversam.")

        attributions = attribution_scene(
            units,
            candidates,
            scene=scene,
            character_profiles=_PROFILES,
            _chat_fn=lambda msgs: _fake_chat_success(),
        )

        assert len(attributions) == 2
        assert attributions[0].primary == "maria"
        assert attributions[1].primary == "joao"

    def test_explicit_dialogue_chained(self) -> None:
        """Chained dialogue (A says X, B says Y) resolves correctly."""
        units = [
            InterpretUnit(index=0, text="— Vamos embora — disse Maria."),
            InterpretUnit(index=1, text="— Não posso — respondeu João."),
        ]
        candidates: list[Candidate] = [
            Candidate(speaker_id="maria", score=0.85, evidence=[]),
            Candidate(speaker_id="joao", score=0.80, evidence=[]),
        ]
        scene = Scene(scene_id="scene-002", text="Diálogo encadeado.")

        attributions = attribution_scene(
            units,
            candidates,
            scene=scene,
            character_profiles=_PROFILES,
            _chat_fn=lambda msgs: _fake_chat_success(),
        )

        assert attributions[0].primary == "maria"
        assert attributions[1].primary == "joao"

    def test_fallback_to_narrator_on_invalid_json(self) -> None:
        """Invalid attribution JSON falls back to narrator for all units."""
        units = [
            InterpretUnit(index=0, text="Narrou-se a história."),
            InterpretUnit(index=1, text="Mais narração."),
        ]
        candidates: list[Candidate] = []
        scene = Scene(scene_id="scene-003", text="Texto sem diálogo.")

        attributions = attribution_scene(
            units,
            candidates,
            scene=scene,
            character_profiles={},
            _chat_fn=lambda msgs: _fake_chat_fails(),
        )

        assert len(attributions) == 2
        for attr in attributions:
            assert attr.primary == "narrator"
            assert any(
                e.detail == "attribution_failed" for e in attr.evidence
            )

    def test_padding_for_partial_response(self) -> None:
        """Partial attribution response gets padded with narrator entries."""
        units = [
            InterpretUnit(index=0, text="Primeiro turno."),
            InterpretUnit(index=1, text="Segundo turno."),
        ]
        candidates: list[Candidate] = [
            Candidate(speaker_id="maria", score=0.9, evidence=[]),
        ]
        scene = Scene(scene_id="scene-004", text="Metade.")

        attributions = attribution_scene(
            units,
            candidates,
            scene=scene,
            character_profiles=_PROFILES,
            _chat_fn=lambda msgs: _fake_chat_partial(),
        )

        assert len(attributions) == 2
        assert attributions[0].primary == "maria"
        # Second unit should be padded
        assert attributions[1].primary == "narrator"

    def test_unknown_primary_replaced_with_narrator(self) -> None:
        """Primary speaker not in allowed set is replaced with narrator."""
        units = [
            InterpretUnit(index=0, text="Alguém falou."),
        ]
        candidates: list[Candidate] = [
            Candidate(speaker_id="maria", score=0.9, evidence=[]),
        ]
        scene = Scene(scene_id="scene-005", text="Sem perfil.")

        attributions = attribution_scene(
            units,
            candidates,
            scene=scene,
            character_profiles=_PROFILES,
            _chat_fn=lambda msgs: _fake_chat_invalid_primary(),
        )

        assert attributions[0].primary == "narrator"

    def test_cache_hit(self, tmp_path: Path) -> None:
        """Attribution cache is read/written correctly."""
        units = [InterpretUnit(index=0, text="Cache test.")]
        scene = Scene(scene_id="scene-cache", text="Cache.")
        profiles_hash = "abc123"

        # Write cache first
        mock_attributions = [
            DialogueAttribution(
                primary="maria",
                ranked_candidates=["maria"],
                evidence=[],
            )
        ]
        _write_attribution_cache(
            scene, profiles_hash, ["maria"], mock_attributions, tmp_path
        )

        # Read cache — should return cached attributions
        cached = _read_attribution_cache(scene, profiles_hash, ["maria"], tmp_path)
        assert cached is not None
        assert len(cached) == 1
        assert cached[0].primary == "maria"

    def test_cache_miss_when_no_file(self, tmp_path: Path) -> None:
        """No cache file returns None."""
        scene = Scene(scene_id="scene-nocache", text="No cache.")
        result = _read_attribution_cache(scene, "xyz", ["maria"], tmp_path)
        assert result is None

    def test_cache_disabled_when_no_dir(self) -> None:
        """No cache written when cache_dir is None."""
        units = [InterpretUnit(index=0, text="No dir.")]
        scene = Scene(scene_id="scene-nodir", text="No dir.")

        def fake_no_cache_fn(messages: list[dict[str, str]]) -> str:
            # Return valid JSON with a single attribution
            return json.dumps({"attributions": [{"primary": "maria"}]})

        attributions = attribution_scene(
            units,
            [Candidate(speaker_id="maria", score=0.9)],
            scene=scene,
            character_profiles=_PROFILES,
            cache_dir=None,
            _chat_fn=fake_no_cache_fn,
        )
        # Should still work, just no caching
        assert len(attributions) == 1
