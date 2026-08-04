"""Deterministic turn tracker for hybrid speaker attribution.

Assigns speaker_id to dialogue units via circular rotation between
active characters, with ``focus_entity`` as the first-turn anchor.

Operates per-scene and maintains turn state:
  1. 0 active speakers → narrator for all dialogue
  2. 1 active speaker → that character for all dialogue
  3. 2+ active speakers → circular rotation (A, B, A, B...)
  4. ``focus_entity`` anchors the first dialogue turn of a new block
  5. Units classified as "narration" or "indirect_dialogue" are ignored
  6. Block transitions detected via ``SceneGraph.edges`` or ``focus_entity``

Returns ``list[TurnAttribution]`` — one per unit.
"""

from __future__ import annotations

from audiobook_ai.llm.scene_graph import SceneGraph
from audiobook_ai.models.cast import (
    EvidenceEntry,
    EvidenceType,
    TurnAttribution,
    UnitClassification,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TurnTracker:
    """Deterministic turn tracker for scene-level speaker attribution.

    Attributes:
        focus_entity: The primary entity in focus for this scene.
        scene_graph: Optional scene graph for block transition detection.
    """

    def __init__(
        self,
        focus_entity: str | None = None,
        scene_graph: SceneGraph | None = None,
    ) -> None:
        """Initialize the TurnTracker.

        Args:
            focus_entity: The entity in focus (anchors first turn of a block).
            scene_graph: Optional scene graph for edge-based transition detection.
        """
        self.focus_entity = focus_entity
        self.scene_graph = scene_graph

    def track(
        self,
        scene_units: list[UnitClassification],
        active_speakers: list[str],
        focus_entity: str | None = None,
        scene_graph: SceneGraph | None = None,
    ) -> list[TurnAttribution]:
        """Assign speaker_id to dialogue units via deterministic rotation.

        Args:
            scene_units: Classified units for the scene.
            active_speakers: List of known character speaker_ids.
            focus_entity: Entity in focus (overrides instance default).
            scene_graph: Scene graph for block transition detection.

        Returns:
            List of ``TurnAttribution`` — one per unit index.
        """
        focus = focus_entity or self.focus_entity
        graph = scene_graph or self.scene_graph
        block_transitions = detect_block_transitions(scene_units, graph)

        # Determine speaker pool based on active count.
        dialogue_units = [
            (i, unit) for i, unit in enumerate(scene_units)
            if unit.classification.value in (
                "explicit_dialogue",
                "ambiguous",
            )
        ]

        if not active_speakers:
            # Rule 1: 0 active → all dialogue units → narrator.
            return [
                TurnAttribution(
                    unit_index=i,
                    speaker_id="narrator",
                    confidence=0.5,
                    evidence=[
                        EvidenceEntry(
                            type=EvidenceType.TURN_TRACKER,
                            detail="no_active_speakers",
                        )
                    ],
                )
                for i, _ in dialogue_units
            ]

        if len(active_speakers) == 1:
            # Rule 2: 1 active → all dialogue units → that character.
            speaker_id = active_speakers[0]
            return [
                TurnAttribution(
                    unit_index=i,
                    speaker_id=speaker_id,
                    confidence=1.0,
                    evidence=[
                        EvidenceEntry(
                            type=EvidenceType.TURN_TRACKER,
                            detail="single_active_speaker",
                        )
                    ],
                )
                for i, _ in dialogue_units
            ]

        # Rule 3: 2+ active speakers → circular rotation.
        speakers = list(active_speakers)
        rotation_idx = 0
        results: dict[int, TurnAttribution] = {}

        for i, _ in dialogue_units:
            # Check if this is a block transition.
            is_block_start = i in block_transitions
            if is_block_start and focus and focus in speakers:
                # Focus entity gets the first turn of a new block.
                current_speaker = focus
                rotation_idx = speakers.index(focus) + 1
            else:
                current_speaker = speakers[rotation_idx % len(speakers)]
                rotation_idx += 1

            results[i] = TurnAttribution(
                unit_index=i,
                speaker_id=current_speaker,
                confidence=0.9 if is_block_start else 0.8,
                evidence=[
                    EvidenceEntry(
                        type=EvidenceType.TURN_TRACKER,
                        detail="rotation" if not is_block_start else "block_transition",
                    )
                ],
            )

        # Build full-length result list (pads non-dialogue units).
        return _build_full_results(scene_units, results)

    def track_units(
        self,
        dialogue_indices: list[int],
        active_speakers: list[str],
        focus_entity: str | None = None,
    ) -> list[TurnAttribution]:
        """Track dialogue units given explicit indices (convenience wrapper).

        Args:
            dialogue_indices: Ordered indices of dialogue units.
            active_speakers: List of known character speaker_ids.
            focus_entity: Entity in focus.

        Returns:
            List of ``TurnAttribution`` for the given indices.
        """
        # Delegate to full track when we have UnitClassifications.
        # This is a simpler path for cases where callers already have indices.
        if not active_speakers:
            return [
                TurnAttribution(
                    unit_index=idx,
                    speaker_id="narrator",
                    confidence=0.5,
                    evidence=[
                        EvidenceEntry(
                            type=EvidenceType.TURN_TRACKER,
                            detail="no_active_speakers",
                        )
                    ],
                )
                for idx in dialogue_indices
            ]

        if len(active_speakers) == 1:
            speaker_id = active_speakers[0]
            return [
                TurnAttribution(
                    unit_index=idx,
                    speaker_id=speaker_id,
                    confidence=1.0,
                    evidence=[
                        EvidenceEntry(
                            type=EvidenceType.TURN_TRACKER,
                            detail="single_active_speaker",
                        )
                    ],
                )
                for idx in dialogue_indices
            ]

        speakers = list(active_speakers)
        rotation_idx = 0
        results: list[TurnAttribution] = []

        for idx in dialogue_indices:
            current_speaker = speakers[rotation_idx % len(speakers)]
            rotation_idx += 1
            results.append(
                TurnAttribution(
                    unit_index=idx,
                    speaker_id=current_speaker,
                    confidence=0.8,
                    evidence=[
                        EvidenceEntry(
                            type=EvidenceType.TURN_TRACKER,
                            detail="rotation",
                        )
                    ],
                )
            )

        return results


def detect_block_transitions(
    units: list[UnitClassification],
    graph: SceneGraph | None = None,
) -> list[int]:
    """Detect indices of units that start new blocks (conversational shifts).

    Uses ``SceneGraph.edges`` and ``focus_entity`` to determine block
    boundaries. Returns indices of units that begin a new block.

    Args:
        units: Classified units for the scene.
        graph: Optional scene graph for edge-based detection.

    Returns:
        List of unit indices that start new blocks.
    """
    if graph is None:
        # No graph provided → no block transitions.
        return []

    if not graph.edges:
        # No edges in graph → first dialogue unit starts the only block.
        dialogue_indices = [
            i for i, u in enumerate(units)
            if u.classification.value in ("explicit_dialogue", "ambiguous")
        ]
        return dialogue_indices[:1]

    # Build a mapping: edge target → source entity id.
    target_source: dict[str, str] = {}
    for edge in graph.edges:
        if edge.target:
            target_source[edge.target] = edge.source

    if not target_source:
        return []

    # If the scene graph has a focus_entity, the first dialogue unit
    # is always a block start.
    transitions: list[int] = []
    dialogue_indices = [
        i for i, u in enumerate(units)
        if u.classification.value in ("explicit_dialogue", "ambiguous")
    ]

    if dialogue_indices:
        transitions.append(dialogue_indices[0])

    return transitions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_full_results(
    scene_units: list[UnitClassification],
    dialogue_attribution: dict[int, TurnAttribution],
) -> list[TurnAttribution]:
    """Build a full-length list of TurnAttribution for all units.

    Dialogue units get their attribution from the tracker.
    Non-dialogue units (narration, indirect_dialogue) get narrator
    attribution with low confidence.

    Args:
        scene_units: All classified units.
        dialogue_attribution: Dialogue unit attributions (index → TurnAttribution).

    Returns:
        Full list of ``TurnAttribution`` — one per unit index.
    """
    results: list[TurnAttribution] = []
    for idx, unit in enumerate(scene_units):
        if idx in dialogue_attribution:
            results.append(dialogue_attribution[idx])
        else:
            results.append(
                TurnAttribution(
                    unit_index=idx,
                    speaker_id="narrator",
                    confidence=0.3,
                    evidence=[
                        EvidenceEntry(
                            type=EvidenceType.TURN_TRACKER,
                            detail=unit.classification.value,
                        )
                    ],
                )
            )
    return results
