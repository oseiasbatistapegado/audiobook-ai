"""Normalize imperfect LLM JSON before schema validation."""

from __future__ import annotations

import re
from typing import Any

# After lowercasing and replacing , / - / space with _, map to canonical keys.
_DIALOGUE_KEY_ALIASES: dict[str, str] = {
    "speaker_id": "speaker_id",
    "speakerid": "speaker_id",
    "speaker": "speaker_id",
    "speaker_": "speaker_id",
    "speaker_name": "speaker_name",
    "speakername": "speaker_name",
    "emotion": "emotion",
    "text": "text",
}

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def repair_llm_json_text(raw: str) -> str:
    """Apply minimal mechanical JSON fixes (trailing commas). Does not invent content."""
    return _TRAILING_COMMA.sub(r"\1", raw)


def _normalize_key(key: str) -> str:
    return (
        str(key)
        .strip()
        .casefold()
        .replace(",", "_")
        .replace("-", "_")
        .replace(" ", "_")
    )


def sanitize_llm_chapter_payload(data: Any) -> Any:
    """Fix common LLM key typos in chapter interpretation JSON.

    Examples recovered:
    - ``speaker,Id`` / ``speakerId`` → ``speaker_id``
    - ``Speaker_Name`` → ``speaker_name``
    """
    if not isinstance(data, dict):
        return data
    out = dict(data)
    dialogues = out.get("dialogues")
    if isinstance(dialogues, list):
        out["dialogues"] = [
            _sanitize_dialogue(item) if isinstance(item, dict) else item
            for item in dialogues
        ]
    return out


def _sanitize_dialogue(item: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in item.items():
        canonical = _DIALOGUE_KEY_ALIASES.get(_normalize_key(key))
        if canonical is None:
            # Keep unknown keys for forward-compat; Pydantic will ignore extras.
            cleaned[key] = value
            continue
        # Prefer the first non-empty value if duplicates appear.
        if canonical in cleaned and cleaned[canonical] not in (None, ""):
            continue
        cleaned[canonical] = value
    return cleaned
