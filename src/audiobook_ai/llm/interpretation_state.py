"""InterpretationState — single object of state shared across all pipeline stages.

Each stage adds data to the state without modifying data from previous stages
(immutability by phase). The state is serializable per-scene for debugging
and can be persisted to disk for resume support.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from audiobook_ai import config
from audiobook_ai.models.cast import (
    CharacterProfile,
    DialogueAttribution,
    TurnAttribution,
    UnitClassification,
)
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.scene import Scene


class InterpretationState(BaseModel):
    """AST-like state object shared across all pipeline stages.

    Each stage appends data without modifying data from earlier stages:
    - Phase 0: scenes (scene segmentation)
    - Phase 1: characters + character_profiles (cast discovery)
    - Phase 3: scene_graphs (per-scene)
    - Phase 4: candidates (per-scene)
    - Phase 5: attributions (per-scene)
    - Phase 6: qa_status, rejected_units
    - Phase 7: interpretations (per-scene)
    """

    # Phase 0: Scene Segmentation
    scenes: list[Scene] = Field(default_factory=list)

    # Phase 1: Cast Discovery
    characters: list[Any] = Field(default_factory=list)
    character_profiles: dict[str, CharacterProfile] = Field(
        default_factory=dict,
    )

    # Phase 3: Scene Graph (per-scene)
    scene_graphs: dict[str, Any] = Field(default_factory=dict)

    # Phase 3b: Unit Classification (per-scene)
    unit_classifications: dict[str, list[UnitClassification]] = Field(
        default_factory=dict,
    )

    # Phase 4: Candidate Generator (per-scene)
    candidates: dict[str, list[Any]] = Field(default_factory=dict)

    # Phase 5b: Turn Tracking (per-scene)
    turn_attributions: dict[str, list[TurnAttribution]] = Field(
        default_factory=dict,
    )

    # Phase 5: Attribution (per-scene)
    attributions: dict[str, list[DialogueAttribution]] = Field(
        default_factory=dict,
    )

    # Phase 6: QA Local
    qa_status: dict[str, list[str]] = Field(default_factory=dict)
    rejected_units: set[tuple[str, int]] = Field(default_factory=set)

    # Phase 7: Interpretation
    interpretations: dict[str, list[Dialogue]] = Field(default_factory=dict)

    def dump_scene(self, scene_id: str) -> dict[str, Any]:
        """Return serialised state for a specific scene.

        Args:
            scene_id: The scene identifier.

        Returns:
            Dict with all accumulated data for this scene.
        """
        return {
            "scene_id": scene_id,
            "scenes": [s.model_dump(mode="json") for s in self.scenes],
            "character_profiles": {
                cid: cp.model_dump(mode="json")
                for cid, cp in self.character_profiles.items()
            },
            "scene_graph": self.scene_graphs.get(scene_id),
            "candidates": self.candidates.get(scene_id),
            "attributions": [
                a.model_dump(mode="json")
                for a in self.attributions.get(scene_id, [])
            ],
            "qa_status": self.qa_status.get(scene_id),
            "interpretations": [
                d.model_dump(mode="json")
                for d in self.interpretations.get(scene_id, [])
            ],
        }

    def mark_rejected(self, scene_id: str, unit_index: int) -> None:
        """Mark a unit as needing review."""
        self.rejected_units.add((scene_id, unit_index))
        status_key = scene_id
        self.qa_status.setdefault(status_key, []).append("needs_review")

    # -- persistence (Group 13) --

    def save_scene(self, scene_id: str, out_dir: Path) -> Path:
        """Persist the current state for *scene_id* to disk.

        Writes ``state_scene_<scene_id>.json`` inside *out_dir*.

        Args:
            scene_id: The scene identifier.
            out_dir: Directory to write the state file into.

        Returns:
            The path where the state was written.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"state_scene_{scene_id}.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def load_scene(cls, path: Path) -> InterpretationState | None:
        """Load an ``InterpretationState`` from a previously saved file.

        Args:
            path: Path to the saved state file.

        Returns:
            The deserialized state, or ``None`` if the file does not exist.
        """
        if not path.is_file():
            return None
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover — defensive guard
            return None

    def save_interpretation_state(self, out_dir: Path) -> Path:
        """Persist the *entire* interpretation state to disk.

        Writes ``interpretation_state.json`` inside *out_dir*.

        Args:
            out_dir: Directory to write the state file into.

        Returns:
            The path where the state was written.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "interpretation_state.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    # -- debug dump (Group 14) --

    def dump_scene_debug(self, scene_id: str) -> dict[str, Any]:
        """Return a serialised debug snapshot for a specific scene.

        Contains accumulated data from all pipeline stages up to the current
        point of processing.  The caller should gate this behind
        ``config.DEBUG_STATE_DUMP``.

        Args:
            scene_id: The scene identifier.

        Returns:
            Dict with all accumulated data for this scene, plus a ``_meta``
            section with pipeline stage names.
        """
        return {
            "_meta": {
                "scene_id": scene_id,
                "num_scenes": len(self.scenes),
                "num_characters": len(self.characters),
                "num_profiles": len(self.character_profiles),
                "num_graphs": len(self.scene_graphs),
                "num_classifications": sum(
                    len(v) for v in self.unit_classifications.values()
                ),
                "num_turns": sum(
                    len(v) for v in self.turn_attributions.values()
                ),
                "num_candidates": sum(
                    len(v) for v in self.candidates.values()
                ),
                "num_attributions": sum(
                    len(v) for v in self.attributions.values()
                ),
                "num_interpretations": sum(
                    len(v) for v in self.interpretations.values()
                ),
                "num_rejected": len(self.rejected_units),
            },
            "scenes": [s.model_dump(mode="json") for s in self.scenes],
            "character_profiles": {
                cid: cp.model_dump(mode="json")
                for cid, cp in self.character_profiles.items()
            },
            "scene_graph": self.scene_graphs.get(scene_id),
            "unit_classifications": [
                uc.model_dump(mode="json")
                for uc in self.unit_classifications.get(scene_id, [])
            ],
            "turn_attributions": [
                ta.model_dump(mode="json")
                for ta in self.turn_attributions.get(scene_id, [])
            ],
            "candidates": self.candidates.get(scene_id),
            "attributions": [
                a.model_dump(mode="json")
                for a in self.attributions.get(scene_id, [])
            ],
            "qa_status": self.qa_status.get(scene_id),
            "interpretations": [
                d.model_dump(mode="json")
                for d in self.interpretations.get(scene_id, [])
            ],
        }

    def write_debug_scene(self, scene_id: str, out_dir: Path) -> Path | None:
        """Write a debug JSON for *scene_id* when ``DEBUG_STATE_DUMP`` is on.

        Writes ``debug_scene_<scene_id>.json`` inside *out_dir*.

        Args:
            scene_id: The scene identifier.
            out_dir: Directory to write the debug file into.

        Returns:
            The path where the debug file was written, or ``None`` if debug
            dumps are disabled.
        """
        if not config.DEBUG_STATE_DUMP:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"debug_scene_{scene_id}.json"
        path.write_text(
            json.dumps(self.dump_scene_debug(scene_id), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path
