"""Cache fingerprint functions for attribution and interpretation.

Each function returns a deterministic SHA-256 hex digest keyed by the
provided identifiers so that caches can be invalidated when policy
versions or scene content change.
"""

from __future__ import annotations

import hashlib

from audiobook_ai import config
from audiobook_ai.models.scene import Scene


def attribution_cache_key(
    scene: Scene,
    *,
    character_profiles_hash: str,
    candidate_generator_version: str = "v1",
    attribution_policy_version: str | None = None,
) -> str:
    """Return a deterministic cache key for attribution of *scene*.

    Args:
        scene: The scene being attributed.
        character_profiles_hash: Hash of the character profiles dict.
        candidate_generator_version: Current candidate generator policy version.
        attribution_policy_version: Current attribution policy version.

    Returns:
        Hex SHA-256 digest.
    """
    version = attribution_policy_version or config.ATTRIBUTION_POLICY_VERSION
    units_str = "|".join(scene.units)
    digest = hashlib.sha256(
        f"{scene.scene_id}\n{scene.text}\n{units_str}\n"
        f"{character_profiles_hash}\n"
        f"{candidate_generator_version}\n"
        f"{version}"
        .encode("utf-8")
    ).hexdigest()
    return f"attr-{digest}"


def interpretation_cache_key(
    scene: Scene,
    *,
    attribution_cache_key: str,
    prompt_version: str = "v1",
    adaptation_policy_version: str = "v1",
) -> str:
    """Return a deterministic cache key for interpretation of *scene*.

    Attribution cache key is embedded so that a cache invalidation at the
    attribution layer propagates to interpretation.

    Args:
        scene: The scene being interpreted.
        attribution_cache_key: The attribution cache key for this scene.
        prompt_version: Current interpretation prompt version.
        adaptation_policy_version: Current adaptation policy version.

    Returns:
        Hex SHA-256 digest.
    """
    units_str = "|".join(scene.units)
    digest = hashlib.sha256(
        f"{scene.scene_id}\n{scene.text}\n{units_str}\n"
        f"{attribution_cache_key}\n"
        f"{prompt_version}\n"
        f"{adaptation_policy_version}"
        .encode("utf-8")
    ).hexdigest()
    return f"interp-{digest}"
