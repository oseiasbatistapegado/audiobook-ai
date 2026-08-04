"""Scene graph builder — deterministic narrative structure per scene.

The Scene Graph models entities, actions, dialogue edges, and focus
within a scene. It is **100% code** (regex + parser), does NOT use LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from audiobook_ai.models.cast import CharacterProfile

# Compiled patterns.
_ENTITY_NAME_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)*"
)


@dataclass(frozen=True)
class EntityNode:
    """A named entity (character) in the scene graph."""

    id: str
    name: str
    first_seen: int = 0
    last_seen: int = 0


@dataclass(frozen=True)
class InteractionEdge:
    """Directed relation between entities in a scene."""

    source: str
    target: str | None = None
    type: str = ""
    scene_id: str = ""


@dataclass
class SceneGraph:
    """Narrative graph for a single scene.

    Contains entities (characters present), edges (interactions),
    focus entity (who is in focus), and turn order.
    """

    scene_id: str = ""
    entities: list[EntityNode] = None  # type: ignore[assignment]
    edges: list[InteractionEdge] = None  # type: ignore[assignment]
    focus_entity: str | None = None
    turn_order: list[dict] = None  # type: ignore[assignment]
    entity_actions: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.entities is None:
            self.entities = []
        if self.edges is None:
            self.edges = []
        if self.turn_order is None:
            self.turn_order = []
        if self.entity_actions is None:
            self.entity_actions = []

    def add_entity(self, entity: EntityNode) -> None:
        """Add or update an entity in the graph."""
        existing = next(
            (e for e in self.entities if e.id == entity.id), None
        )
        if existing is None:
            self.entities.append(entity)
        else:
            # Update last_seen, keep first_seen.
            self.entities[self.entities.index(existing)] = replace(
                existing,
                last_seen=max(existing.last_seen, entity.last_seen),
            )

    def add_edge(self, edge: InteractionEdge) -> None:
        """Add an interaction edge."""
        self.edges.append(edge)


def build_scene_graph(
    scene_units: list[str],
    character_profiles: dict[str, CharacterProfile],
    classifications: list[str] | None = None,
) -> SceneGraph:
    """Build a SceneGraph from scene units and character profiles.

    This is **deterministic** (regex + parser), no LLM.

    Args:
        scene_units: Text units (paragraphs) in the scene.
        character_profiles: Known character profiles (id -> profile).
        classifications: Optional classification results per unit (unused,
            kept for API compat).

    Returns:
        A ``SceneGraph`` for the scene.
    """
    graph = SceneGraph()
    name_to_id: dict[str, str] = {}
    for cid, profile in character_profiles.items():
        name_to_id[profile.name.strip().casefold()] = cid
        for alias in profile.aliases:
            name_to_id[alias.strip().casefold()] = cid

    seen_entities: dict[str, EntityNode] = {}
    action_counter = 0

    for unit_idx, unit in enumerate(scene_units):
        # Extract character names from the unit.
        matched_cid: str | None = None
        for match in _ENTITY_NAME_RE.finditer(unit):
            name = match.group(0).strip()
            name_cf = name.casefold()
            cid = name_to_id.get(name_cf)
            if cid is None:
                continue

            if cid not in seen_entities:
                seen_entities[cid] = EntityNode(
                    id=cid, name=character_profiles[cid].name,
                    first_seen=unit_idx, last_seen=unit_idx,
                )

            # Update last_seen.
            entity = seen_entities[cid]
            seen_entities[cid] = replace(
                entity, last_seen=max(entity.last_seen, unit_idx)
            )
            matched_cid = cid

        # Detect interactions (speech verbs + name).
        _detect_interactions(
            unit, matched_cid, name_to_id, graph
        )
        action_counter += 1

    for entity in seen_entities.values():
        graph.add_entity(entity)

    # Focus entity = most recently seen (or most frequent).
    if seen_entities:
        graph.focus_entity = max(
            seen_entities.values(),
            key=lambda e: e.last_seen,
        ).id

    return graph


def _detect_interactions(
    unit: str,
    cid: str | None,
    name_to_id: dict[str, str],
    graph: SceneGraph,
) -> None:
    """Detect interaction keywords in a unit and add edges."""
    speech_verbs = [
        "disse", "respondeu", "perguntou", "falou", "gritou",
        "sussurrou", "retrucou", "exclamou", "murmurou",
        "olhou", "interrompeu",
    ]

    for verb in speech_verbs:
        pattern = re.compile(
            rf"\b{verb}\s+([A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)*)\b",
            re.IGNORECASE,
        )
        for match in pattern.finditer(unit):
            target_name = match.group(1).strip().casefold()
            target_id = name_to_id.get(target_name)
            if target_id is None:
                continue
            edge = InteractionEdge(
                source=cid or "narrator",
                target=target_id,
                type=verb,
                scene_id=graph.scene_id,
            )
            graph.add_edge(edge)
