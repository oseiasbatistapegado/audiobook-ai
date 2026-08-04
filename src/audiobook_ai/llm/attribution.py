"""Scene-level speaker attribution via Ollama.

Caches per-scene and falls back to ``narrator`` on failure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from audiobook_ai import config
from audiobook_ai.llm.sanitize import repair_llm_json_text
from audiobook_ai.llm.units import InterpretUnit
from audiobook_ai.models.cast import (
    AttributionResponse,
    Candidate,
    CharacterProfile,
    DialogueAttribution,
    EvidenceEntry,
    EvidenceType,
    TurnAttribution,
    UnitClassification,
)
from audiobook_ai.models.scene import Scene
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def attribution_scene(
    units: list[InterpretUnit],
    candidates: list[Candidate],
    *,
    scene: Scene,
    character_profiles: dict[str, CharacterProfile],
    unit_classifications: list[UnitClassification] | None = None,
    resolved_units: list[TurnAttribution] | None = None,
    prompt_path: Path | None = None,
    cache_dir: Path | None = None,
    character_profiles_hash: str = "",
    _chat_fn: object | None = None,
) -> list[DialogueAttribution]:
    """Run Ollama attribution for all units in a scene.

    In hybrid mode, pre-resolved units (from Unit Classifier + Turn Tracker)
    are passed via ``unit_classifications`` and ``resolved_units``. Only
    units classified as ``ambiguous`` are sent to the LLM.

    Args:
        units: Text units in the scene.
        candidates: Pre-computed candidate speakers (from CandidateGenerator).
        scene: The Scene object (for cache key).
        character_profiles: Known character profiles.
        unit_classifications: Optional per-unit classifications.
        resolved_units: Optional pre-resolved TurnAttribution results.
        prompt_path: Path to the attribution prompt file.
        cache_dir: Directory for attribution cache files.
        character_profiles_hash: Stable hash of profiles (cache key fragment).
        _chat_fn: Callable ``list[dict] -> str`` for LLM calls (mockable).

    Returns:
        List of ``DialogueAttribution`` — one per unit.
    """
    # Build candidate list for the prompt.
    allowed_ids = sorted({c.speaker_id for c in candidates} | {"narrator"})

    # Determine which units need LLM attribution.
    ambiguous_indices: list[int] = []
    if unit_classifications:
        for uc in unit_classifications:
            if uc.classification.value == "ambiguous":
                ambiguous_indices.append(uc.unit_index)
    else:
        # No classifications — all units go to LLM (legacy mode).
        ambiguous_indices = list(range(len(units)))

    # If all units are resolved by code, return early.
    resolved_map: dict[int, DialogueAttribution] = {}
    if resolved_units:
        for ra in resolved_units:
            resolved_map[ra.unit_index] = DialogueAttribution(
                primary=ra.speaker_id,
                ranked_candidates=[ra.speaker_id, "narrator"],
                evidence=ra.evidence,
                reason=f"resolved_by_{ra.evidence[0].detail if ra.evidence else 'turn_tracker'}",
            )

    # If no ambiguous units, return resolved map as-is.
    if not ambiguous_indices:
        all_attributions = _build_full_attributions(units, resolved_map)
        # Write cache even for no-LLM scene.
        _write_attribution_cache(
            scene,
            character_profiles_hash,
            allowed_ids,
            all_attributions,
            cache_dir,
        )
        return all_attributions

    # Build user payload with scene context for disambiguation.
    user_payload = json.dumps(
        {
            "scene_id": scene.scene_id,
            "scene_text": scene.text[:500] if scene.text else "",
            "units": [u.text for u in units],
            "allowed_speakers": allowed_ids,
            "candidate_speakers": [
                {"id": c.speaker_id, "score": c.score} for c in candidates
            ],
            "resolved_units": [
                {"index": idx, "speaker": ra.primary}
                for idx, ra in sorted(resolved_map.items())
            ],
            "ambiguous_indices": ambiguous_indices,
            "unit_classifications": [
                {"index": uc.unit_index, "classification": uc.classification.value}
                for uc in unit_classifications
            ]
            if unit_classifications
            else [],
        },
        ensure_ascii=False,
        indent=2,
    )

    # Load system prompt.
    system_prompt = _load_attribution_prompt(prompt_path)

    # Check attribution cache.
    cached = _read_attribution_cache(
        scene,
        character_profiles_hash,
        allowed_ids,
        cache_dir,
    )
    if cached is not None:
        logger.info("attribution cache hit scene=%s", scene.scene_id)
        return cached

    # Build messages for Ollama.
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_payload},
    ]

    max_attempts = config.LLM_INTERPRET_MAX_ATTEMPTS
    llm_attributions: dict[int, DialogueAttribution] = {}

    for attempt in range(1, max_attempts + 1):
        raw = _call_chat(messages, _chat_fn)
        if not raw.strip():
            logger.warning(
                "attribution empty response scene=%s attempt=%s",
                scene.scene_id,
                attempt,
            )
            if attempt >= max_attempts:
                break
            continue

        parsed = _try_validate_attribution(
            raw,
            [units[i] for i in ambiguous_indices],
            allowed_ids,
            attempt,
        )
        if parsed is not None:
            for attr_idx, attr in enumerate(parsed):
                orig_idx = ambiguous_indices[attr_idx]
                llm_attributions[orig_idx] = attr
            break

        if attempt >= max_attempts:
            break

        messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your previous attribution response failed validation. "
                    "Reply again with JSON only matching the schema."
                ),
            },
        ]

    # Build full attribution list: resolved + LLM + fallback for failures.
    if not llm_attributions and ambiguous_indices:
        logger.warning(
            "attribution fell back to narrator scene=%s",
            scene.scene_id,
        )
        for idx in ambiguous_indices:
            llm_attributions[idx] = DialogueAttribution(
                primary="narrator",
                ranked_candidates=["narrator"],
                evidence=[
                    EvidenceEntry(
                        type=EvidenceType.EXPLICIT,
                        detail="attribution_failed",
                    )
                ],
                reason="attribution_failed",
            )

    all_attributions = _build_full_attributions(units, resolved_map, llm_attributions)

    # Write attribution cache.
    _write_attribution_cache(
        scene,
        character_profiles_hash,
        allowed_ids,
        all_attributions,
        cache_dir,
    )

    return all_attributions


def _build_full_attributions(
    units: list[InterpretUnit],
    resolved_map: dict[int, DialogueAttribution],
    llm_attributions: dict[int, DialogueAttribution] | None = None,
) -> list[DialogueAttribution]:
    """Build a full list of DialogueAttribution for all units.

    Resolved units get their pre-computed attribution. Ambiguous units
    get their LLM attribution or a narrator fallback.

    Args:
        units: All text units in the scene.
        resolved_map: Pre-resolved attributions (index → DialogueAttribution).
        llm_attributions: LLM attributions for ambiguous units.

    Returns:
        Full list of ``DialogueAttribution`` — one per unit.
    """
    llm = llm_attributions or {}
    attributions: list[DialogueAttribution] = []

    for i, unit in enumerate(units):
        if i in resolved_map:
            attributions.append(resolved_map[i])
        elif i in llm:
            attributions.append(llm[i])
        else:
            attributions.append(
                DialogueAttribution(
                    primary="narrator",
                    ranked_candidates=["narrator"],
                    evidence=[
                        EvidenceEntry(
                            type=EvidenceType.SCENE_CONTEXT,
                            detail="narration_default",
                        )
                    ],
                    reason="narration",
                )
            )

    return attributions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_attribution_prompt(path: Path | None = None) -> str:
    """Load the attribution prompt from disk."""
    target = path or (_PROMPTS_DIR / config.LLM_ATTRIBUTION_PROMPT_FILE)
    if not target.is_file():
        raise FileNotFoundError(f"Attribution prompt file missing: {target}")
    return target.read_text(encoding="utf-8")


def _call_chat(messages: list[dict[str, str]], fn: object | None) -> str:
    """Call the chat function to get an LLM response."""
    if fn is not None:
        return fn(messages)  # type: ignore[no-any-return]
    raise RuntimeError("attribution_scene requires _chat_fn")


def _try_validate_attribution(
    raw: str,
    units: list[InterpretUnit],
    allowed_ids: list[str],
    attempt: int,
) -> list[DialogueAttribution] | None:
    """Parse and validate the attribution JSON response."""
    try:
        text = repair_llm_json_text(raw.strip())
        data = json.loads(text)
        resp = AttributionResponse.model_validate(data)

        # Ensure we have one attribution per unit.
        if len(resp.attributions) < len(units):
            while len(resp.attributions) < len(units):
                resp.attributions.append(
                    DialogueAttribution(
                        primary="narrator",
                        ranked_candidates=["narrator"],
                        evidence=[
                            EvidenceEntry(
                                type=EvidenceType.SCENE_CONTEXT,
                                detail="padding_narrator",
                            )
                        ],
                        reason="padding_missing_unit",
                    )
                )

        # Validate primary speakers are in allowed set.
        for attr in resp.attributions:
            if attr.primary not in allowed_ids:
                logger.warning(
                    "attribution primary not in allowed set "
                    "scene=%s primary=%s attempt=%s",
                    "unknown",
                    attr.primary,
                    attempt,
                )
                attr.primary = "narrator"

        return resp.attributions
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(
            "attribution validation failed attempt=%s error=%s",
            attempt,
            exc,
        )
        return None


def _attribution_cache_file_path(
    scene: Scene,
    character_profiles_hash: str,
    allowed_ids: list[str],
    unit_classifier_version: str,
    turn_tracker_version: str,
    cache_dir: Path | None,
) -> Path | None:
    """Compute the attribution cache file path."""
    if cache_dir is None or not config.LLM_CACHE_ENABLED:
        return None
    key = _attribution_cache_key(
        scene,
        character_profiles_hash,
        candidate_generator_version=config.CANDIDATE_GENERATOR_VERSION,
        unit_classifier_version=unit_classifier_version,
        turn_tracker_version=turn_tracker_version,
        attribution_policy_version=config.ATTRIBUTION_POLICY_VERSION,
    )
    return cache_dir / f"attr-{key}.json"


def _attribution_cache_key(
    scene: Scene,
    character_profiles_hash: str,
    candidate_generator_version: str,
    unit_classifier_version: str,
    turn_tracker_version: str,
    attribution_policy_version: str,
) -> str:
    """Stable cache key for attribution of a scene."""
    digest = hashlib.sha256(
        (
            f"{scene.scene_id}\n{scene.compute_text_hash()}\n"
            f"profiles={character_profiles_hash}\n"
            f"candidate_gen={candidate_generator_version}\n"
            f"unit_classifier={unit_classifier_version}\n"
            f"turn_tracker={turn_tracker_version}\n"
            f"attr_policy={attribution_policy_version}"
        ).encode("utf-8")
    ).hexdigest()
    return digest


def _read_attribution_cache(
    scene: Scene,
    character_profiles_hash: str,
    allowed_ids: list[str],
    cache_dir: Path | None,
) -> list[DialogueAttribution] | None:
    """Read attribution cache from disk."""
    path = _attribution_cache_file_path(
        scene, character_profiles_hash, allowed_ids,
        config.UNIT_CLASSIFIER_VERSION, config.TURN_TRACKER_VERSION,
        cache_dir,
    )
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            DialogueAttribution.model_validate(item)
            for item in data.get("attributions", [])
        ]
    except (json.JSONDecodeError, ValidationError):
        logger.warning("ignoring invalid attribution cache path=%s", path)
        return None


def _write_attribution_cache(
    scene: Scene,
    character_profiles_hash: str,
    allowed_ids: list[str],
    attributions: list[DialogueAttribution],
    cache_dir: Path | None,
) -> None:
    """Write attribution cache to disk."""
    path = _attribution_cache_file_path(
        scene, character_profiles_hash, allowed_ids,
        config.UNIT_CLASSIFIER_VERSION, config.TURN_TRACKER_VERSION,
        cache_dir,
    )
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"attributions": [a.model_dump() for a in attributions]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("wrote attribution cache path=%s", path)
