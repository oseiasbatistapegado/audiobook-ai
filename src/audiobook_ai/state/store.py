"""Load and save ``story.json`` as typed ``StoryState``."""

from __future__ import annotations

from pathlib import Path

from audiobook_ai.models.story import StoryState
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)


def load_story_state(path: Path) -> StoryState:
    """Load ``StoryState`` from disk, or return an empty state if missing."""
    if not path.is_file():
        logger.info("story state missing; starting empty path=%s", path)
        return StoryState()
    logger.info("loading story state path=%s", path)
    return StoryState.model_validate_json(path.read_text(encoding="utf-8"))


def save_story_state(state: StoryState, path: Path) -> None:
    """Persist ``StoryState`` as JSON under the work-dir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info("saved story state path=%s characters=%s", path, len(state.characters))
