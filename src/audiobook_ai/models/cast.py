"""Cast discovery and attribution models."""

from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Chapter cast discovery (Pass 1)
# ---------------------------------------------------------------------------


class ChapterParticipation(str, Enum):
    """Chapter-local speaking status — not persisted on global Character."""

    SPEAKER = "speaker"
    POSSIBLE_SPEAKER = "possible_speaker"
    MENTIONED = "mentioned"


class ChapterCastEntry(BaseModel):
    """One character in a chapter cast with chapter-local participation.

    Only id, name, aliases, participation — no speaker_profile or persistent
    inference.  Cast Discovery is "cold": it does NOT invent traits like
    "fria" or "agressiva".
    """

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    participation: ChapterParticipation = ChapterParticipation.SPEAKER


class LLMCastDiscoveryResponse(BaseModel):
    """Validated JSON-only response for Pass 1 cast discovery."""

    characters: list[ChapterCastEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# CharacterProfile — immutable, cross-chapter facts
# ---------------------------------------------------------------------------


class CharacterProfile(BaseModel):
    """Immutable facts about a character (persisted across chapters)."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    gender: str | None = None
    role: str = "secondary"  # POV / secondary / teacher / etc.
    known_names: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SceneProfile — temporal, per-scene inferences
# ---------------------------------------------------------------------------


class SceneProfile(BaseModel):
    """Temporal profile of a character within a single scene."""

    mood: str | None = None
    speech_patterns: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)
    active_actions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Interaction graph (per-scene edges between characters)
# ---------------------------------------------------------------------------


class InteractionEdge(BaseModel):
    """Directed interpersonal relation within a scene."""

    source: str = Field(min_length=1)
    target: str | None = None
    type: str = Field(min_length=1)  # e.g. "respondeu", "interrupção", "olha"
    scene_id: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Evidence entries — typed evidence from CandidateGenerator / Attribution
# ---------------------------------------------------------------------------


class EvidenceType(str, Enum):
    EXPLICIT = "EXPLICIT"
    TURN_ORDER = "TURN_ORDER"
    SCENE_CONTEXT = "SCENE_CONTEXT"
    ALIAS_MATCH = "ALIAS_MATCH"
    EMBEDDING = "EMBEDDING"
    RELATIONSHIP = "RELATIONSHIP"
    FIRST_PERSON = "FIRST_PERSON"
    TURN_TRACKER = "TURN_TRACKER"


class EvidenceEntry(BaseModel):
    """One piece of evidence for speaker attribution."""

    type: EvidenceType
    detail: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Dialogue attribution (LLM output — who says what)
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    """One candidate speaker for attribution."""

    speaker_id: str = Field(min_length=1)
    score: float
    evidence: list[EvidenceEntry] = Field(default_factory=list)


class DialogueAttribution(BaseModel):
    """Attribution result for one interpret unit."""

    primary: str = Field(min_length=1)  # speaker_id chosen
    ranked_candidates: list[str] = Field(default_factory=list)
    evidence: list[EvidenceEntry] = Field(default_factory=list)
    reason: str = ""


class AttributionResponse(BaseModel):
    """Validated JSON-only response for speaker attribution of a scene."""

    attributions: list[DialogueAttribution] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Segment classification (3 classes)
# ---------------------------------------------------------------------------


class Classification(str, Enum):
    EXPLICIT_DIALOGUE = "explicit_dialogue"
    INDIRECT_DIALOGUE = "indirect_dialogue"
    NARRATION = "narration"
    AMBIGUOUS = "ambiguous"


class SegmentClassification(BaseModel):
    """Classification of a text segment into 3 classes."""

    text: str = Field(min_length=0)
    classification: Classification
    is_indirect: bool = False


# ---------------------------------------------------------------------------
# Unit classification (4 classes — hybrid attribution)
# ---------------------------------------------------------------------------


class UnitClassification(BaseModel):
    """Deterministic classification of one interpret unit."""

    unit_index: int = Field(ge=0)
    classification: Classification
    is_indirect: bool = False


class TurnAttribution(BaseModel):
    """Deterministic turn attribution for one unit (Turn Tracker output)."""

    unit_index: int = Field(ge=0)
    speaker_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Legacy compat
# ---------------------------------------------------------------------------


def character_profile_hash(profiles: dict[str, CharacterProfile]) -> str:
    """Stable hash of a character_profiles dict (cache key fragment)."""
    raw = json.dumps(
        {cid: p.model_dump(mode="json") for cid, p in sorted(profiles.items())},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
