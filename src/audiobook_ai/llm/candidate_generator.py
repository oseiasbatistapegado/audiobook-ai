"""Deterministic candidate generator for speaker attribution.

Cascading pipeline (Steps 0–5), 100% code, no LLM calls:
  0. First-person marker — regex for ``eu``, ``meu``, ``sou`` → implicit
     dialogue signal (no speaker_id assigned)
  1. Explicit name  - regex ``[A-Z][\\w'-]+`` preceded by speech
     verbs -> lookup in ``character_profiles``
  2. Alias match    - regex over ``CharacterProfile.aliases`` -> match in text
  3. Pronoun        - parser of ``ele``/``ela`` -> gender lookup in profiles
  4. Focus entity   - ``SceneGraph.focus_entity`` -> primary candidate
  5. Embedding      - fallback: ``resolve_descriptive_aliases``

Returns ``list[Candidate]`` sorted by descending score.
"""

from __future__ import annotations

import re

from audiobook_ai import config
from audiobook_ai.embeddings.speaker import SpeakerEmbeddingService
from audiobook_ai.llm.scene_graph import SceneGraph
from audiobook_ai.models.cast import Candidate, CharacterProfile, EvidenceEntry, EvidenceType


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Speech-verb + name attribution (Portuguese + English).
_SPEECH_VERB_NAME_RE = re.compile(
    r"(?:disse|respondeu|perguntou|falou|gritou|sussurrou|retrucou|" 
    r"exclamou|murmurou|acrescentou|insistiu|rebateu|" 
    r"said|asked|replied|answered|shouted|whispered)\b" 
    r"\s*" 
    r"(?:" 
    r"([A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)"  # name after verb 
    r"|" 
    r"([\w'-]+)\s+(?:disse|respondeu|perguntou|falou|said|asked|replied)\b"
    r")" 
    r",?",
    re.IGNORECASE,
)

# Pronoun → gender resolver (PT-BR).
_PRONOUN_GENDER_MAP: dict[str, str] = {
    "ele": "masculino",
    "ela": "feminino",
    "seu": "masculino",
    "sua": "feminino",
    "meu": "masculino",
    "minha": "feminino",
}

# Entity name in text (for alias matching).
_ENTITY_NAME_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)*"
)

# First-person pronoun markers (PT-BR).
_FIRST_PERSON_RE = re.compile(
    r"\b(?:eu\s+me|eu\s+meu|eu\s+minha|por\s+que\s+eu|"
    r"sou\s+um\b|sou\s+uma\b|"
    r"\bmeu\b\s+\w+|\bminha\b\s+\w+|"
    r"\bmeu\b|\bminha\b|"
    r"\beu\s+[a-zà-ú])\b",
    re.IGNORECASE,
)


def _resolve_name_to_id(
    name: str,
    profiles: dict[str, CharacterProfile],
) -> str | None:
    """Look up a raw name string against character profiles."""
    name_stripped = name.strip()
    for cid, profile in profiles.items():
        if profile.name.strip().casefold() == name_stripped.casefold():
            return cid
        for alias in profile.aliases:
            if alias.strip().casefold() == name_stripped.casefold():
                return cid
        for known in profile.known_names:
            if known.strip().casefold() == name_stripped.casefold():
                return cid
    return None


def _resolve_pronoun_to_id(
    text: str,
    profiles: dict[str, CharacterProfile],
) -> str | None:
    """Resolve pronouns (ele/ela) to speaker_id via gender lookup."""
    text_lower = text.lower()
    for pronoun, gender in _PRONOUN_GENDER_MAP.items():
        if re.search(rf"\b{pronoun}\b", text_lower):
            for cid, profile in profiles.items():
                if profile.gender and profile.gender.casefold() == gender:
                    return cid
    return None


# ---------------------------------------------------------------------------
# Step 0: First-person marker detection
# ---------------------------------------------------------------------------


def _step_first_person(
    unit_text: str,
    candidates: list[Candidate],
) -> list[Candidate]:
    """Step 0: Detect first-person markers in unit text.

    Returns a single candidate with ``narrator`` as a signal that this
    unit is implicit dialogue (the Turn Tracker will resolve the actual
    speaker). Does NOT assign a specific character speaker_id.

    Matches PT-BR first-person markers: ``eu``, ``meu``, ``minha``,
    ``sou um/uma``, ``por que eu``, ``eu me``, ``eu meu``, ``eu minha``,
    and ``eu <verb>`` patterns.

    Args:
        unit_text: The text unit to analyze.
        candidates: Passed-through (not modified if no match).

    Returns:
        List of ``Candidate`` — one ``narrator`` candidate if a marker
        is found, otherwise the original list unchanged.
    """
    if _FIRST_PERSON_RE.search(unit_text):
        return [
            Candidate(
                speaker_id="narrator",
                score=0.7,
                evidence=[
                    EvidenceEntry(
                        type=EvidenceType.FIRST_PERSON,
                        detail="first_person_marker",
                    )
                ],
            )
        ]
    return candidates


# ---------------------------------------------------------------------------
# Cascade pipeline
# ---------------------------------------------------------------------------


def generate_candidates(
    unit_text: str,
    character_profiles: dict[str, CharacterProfile],
    scene_graph: SceneGraph | None = None,
    *,
    embedding_service: SpeakerEmbeddingService | None = None,
) -> list[Candidate]:
    """Generate ranked speaker candidates for a unit of text.

    Cascading pipeline (Steps 1–5). Each step only fires if all previous
    steps failed to resolve.  The top candidate (highest score) is
    returned first.

    Args:
        unit_text: The text unit to analyze.
        character_profiles: Known character profiles (id -> profile).
        scene_graph: Optional scene graph with focus entity / edges.
        embedding_service: Optional embedding service for Step 5 fallback.

    Returns:
        List of ``Candidate`` objects sorted by descending score.
    """
    candidates: list[Candidate] = []

    # Step 0: First-person marker — signals implicit dialogue.
    # Does NOT assign a speaker_id; just flags that the unit is dialogue
    # (the Turn Tracker will resolve the actual speaker).
    candidates = _step_first_person(unit_text, candidates)
    if candidates:
        # First-person marker found — return early (no further resolution needed).
        return candidates

    # Step 1: Explicit name preceded by speech verbs.
    candidates = _step_explicit_name(unit_text, character_profiles, candidates)
    if candidates:
        return candidates

    # Step 2: Alias match against CharacterProfile.aliases.
    candidates = _step_alias_match(
        unit_text, character_profiles, candidates
    )
    if candidates:
        return candidates

    # Step 3: Pronoun resolver.
    candidates = _step_pronoun(
        unit_text, character_profiles, candidates
    )
    if candidates:
        return candidates

    # Step 4: Focus entity from SceneGraph.
    candidates = _step_focus_entity(
        scene_graph, character_profiles, candidates
    )
    if candidates:
        return candidates

    # Step 5: Embedding fallback (only if no model, degrade silently).
    candidates = _step_embedding(
        unit_text, character_profiles, embedding_service, candidates
    )
    if candidates:
        return candidates

    # All steps failed — return empty list (attribution will fall back).
    return candidates


def _step_explicit_name(
    unit_text: str,
    profiles: dict[str, CharacterProfile],
    candidates: list[Candidate],
) -> list[Candidate]:
    """Step 1: Look for explicit name preceded by speech verbs."""
    for match in _SPEECH_VERB_NAME_RE.finditer(unit_text):
        name = match.group(1) or match.group(2)
        if not name:
            continue
        cid = _resolve_name_to_id(name, profiles)
        if cid is None:
            continue
        candidates.append(Candidate(
            speaker_id=cid,
            score=1.0,
            evidence=[EvidenceEntry(
                type=EvidenceType.EXPLICIT,
                detail=name.strip(),
            )],
        ))
    return candidates


def _step_alias_match(
    unit_text: str,
    profiles: dict[str, CharacterProfile],
    candidates: list[Candidate],
) -> list[Candidate]:
    """Step 2: Match character aliases against the text."""
    text_lower = unit_text.lower()
    for cid, profile in profiles.items():
        for alias in profile.aliases:
            if re.search(
                rf"\b{re.escape(alias.strip())}\b",
                text_lower,
                re.IGNORECASE,
            ):
                candidates.append(Candidate(
                    speaker_id=cid,
                    score=0.9,
                    evidence=[EvidenceEntry(
                        type=EvidenceType.ALIAS_MATCH,
                        detail=alias.strip(),
                    )],
                ))
                break  # one alias match per character
    return candidates


def _step_pronoun(
    unit_text: str,
    profiles: dict[str, CharacterProfile],
    candidates: list[Candidate],
) -> list[Candidate]:
    """Step 3: Resolve pronouns to speaker via gender lookup."""
    cid = _resolve_pronoun_to_id(unit_text, profiles)
    if cid is not None:
        candidates.append(Candidate(
            speaker_id=cid,
            score=0.6,
            evidence=[EvidenceEntry(
                type=EvidenceType.TURN_ORDER,
                detail="pronoun_resolution",
            )],
        ))
    return candidates


def _step_focus_entity(
    graph: SceneGraph | None,
    profiles: dict[str, CharacterProfile],
    candidates: list[Candidate],
) -> list[Candidate]:
    """Step 4: Use SceneGraph focus entity as candidate."""
    if graph is None or graph.focus_entity is None:
        return candidates
    focus_id = graph.focus_entity
    if focus_id not in profiles:
        return candidates
    candidates.append(Candidate(
        speaker_id=focus_id,
        score=0.5,
        evidence=[EvidenceEntry(
            type=EvidenceType.SCENE_CONTEXT,
            detail=f"focus_entity:{graph.focus_entity}",
        )],
    ))
    return candidates


def _step_embedding(
    unit_text: str,
    profiles: dict[str, CharacterProfile],
    embedding_service: SpeakerEmbeddingService | None,
    candidates: list[Candidate],
) -> list[Candidate]:
    """Step 5: Embedding fallback — only if model is available."""
    if embedding_service is None:
        return candidates

    top_k = config.SPEAKER_RESOLUTION_TOP_K
    results = embedding_service.resolve_descriptive_aliases(
        unit_text, list(profiles.values()), top_k=top_k
    )

    for idx, (cid, similarity) in enumerate(results):
        if cid in profiles and similarity >= config.ATTRIBUTION_EMBEDDING_GAP_THRESHOLD:
            candidates.append(Candidate(
                speaker_id=cid,
                score=round(similarity, 4),
                evidence=[EvidenceEntry(
                    type=EvidenceType.EMBEDDING,
                    detail=f"embedding_similarity:{similarity:.4f}",
                )],
            ))
        elif cid not in profiles and cid not in {c.speaker_id for c in candidates}:
            # New character via embedding — record with low confidence.
            candidates.append(Candidate(
                speaker_id=cid,
                score=round(similarity, 4),
                evidence=[EvidenceEntry(
                    type=EvidenceType.EMBEDDING,
                    detail=f"new_character:{similarity:.4f}",
                )],
            ))

    return candidates
