"""Scene segmentation — divide chapter text into narrative scenes.

Scene Segmentation is **fully deterministic**: same input -> same output.
Scenes are identified by heuristics on focus shifts, character entrance/exit,
dialogue breaks, and time/place changes.
"""

from __future__ import annotations

import re

from audiobook_ai.models.scene import Scene

# --- Compiled regex patterns (module-level, shared) ---

_ENTRANCE_EXIT_RE = re.compile(
    r"\b(entrou|saiu|deixou\s+o\s+o\s+local|chegou|partiu|sumiu|"
    r"apareceu|saqueiou)\b",
    re.IGNORECASE,
)

_TIME_PLACE_RE = re.compile(
    r"\b(no\s+intervalo|depois\s+disso|mais\s+tarde|na\s+sequencia|"
    r"mais\s+cedo|naquele\s+momento|naquele\s+dia|naquele\s+horario|"
    r"poucos\s+minutos\s+depois|um\s+instante\s+depois|"
    r"no\s+dia\s+seguinte|naquela\s+noite|naquela\s+manha|"
    r"naquela\s+tarde|na\s+praca|na\s+rua|na\s+escola|"
    r"no\s+patio|na\s+quadra|"
    r"na\s+sala\s+de\s+aula|na\s+cozinha|no\s+quarto)\b",
    re.IGNORECASE,
)

_PARAGRAPH_BREAK_RE = re.compile(r"\n{2,}")

_DASH_DIALOGUE_RE = re.compile(r"^\s*[\u2014\u2013]")


class SceneSegmenter:
    """Deterministic scene segmenter.

    Splits raw chapter text into ``Scene`` objects where each scene typically
    contains 8-20 text units (paragraphs).

    Scene boundaries are detected by:
    - Character entrance/exit (``entrou``, ``saiu``, ``deixou``)
    - Time/place transitions (``no intervalo``, ``depois disso``, ``naquele momento``)
    - Dialogue breaks (new speaker marker)
    - Three or more consecutive newlines
    """

    def __init__(self, max_units_per_scene: int = 20) -> None:
        self.max_units_per_scene = max_units_per_scene

    def segment(self, text: str) -> list[Scene]:
        """Split *text* into scenes.

        Args:
            text: Raw chapter text.

        Returns:
            List of ``Scene`` objects with sequential IDs.
        """
        if not text.strip():
            return []

        paragraphs = [
            p.strip()
            for p in _PARAGRAPH_BREAK_RE.split(text)
            if p.strip()
        ]
        if not paragraphs:
            return []

        scenes: list[Scene] = []
        current_scene = Scene(scene_id="scene-000")

        for i, paragraph in enumerate(paragraphs):
            current_scene.add_unit(paragraph)

            should_split = self._should_end_scene(
                paragraph,
                paragraphs[i + 1] if i + 1 < len(paragraphs) else "",
                current_scene,
            )

            if should_split or len(current_scene.units) >= self.max_units_per_scene:
                if current_scene.units:
                    scenes.append(current_scene)
                current_scene = Scene(
                    scene_id=f"scene-{len(scenes):03d}"
                )
                if not should_split:
                    current_scene.add_unit(paragraph)

        if current_scene.units:
            scenes.append(current_scene)

        return scenes

    def _should_end_scene(
        self,
        current_paragraph: str,
        next_paragraph: str,
        scene: Scene,
    ) -> bool:
        """Return True if the current paragraph likely ends the current scene."""
        if not next_paragraph:
            return True

        # Heuristic 1: Character entrance/exit detected.
        if _ENTRANCE_EXIT_RE.search(
            current_paragraph
        ) or _ENTRANCE_EXIT_RE.search(next_paragraph):
            return True

        # Heuristic 2: Time/place transition.
        if _TIME_PLACE_RE.search(next_paragraph):
            return True

        # Heuristic 3: Dialogue marker at start of next paragraph.
        if _DASH_DIALOGUE_RE.match(next_paragraph):
            return True

        # Heuristic 4: Very short scenes (1 paragraph) should be merged
        # unless we already have content.
        if len(scene.units) >= 2 and len(current_paragraph) < 40:
            return True

        return False


def segment_text(text: str) -> list[Scene]:
    """Convenience function to segment text into scenes.

    Args:
        text: Raw chapter text.

    Returns:
        List of ``Scene`` objects.
    """
    return SceneSegmenter().segment(text)
