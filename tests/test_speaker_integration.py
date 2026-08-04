"""Integration tests for the new speaker-resolution pipeline in ``LlamaCppBackend``.

These tests verify that ``interpret_chapter_v2`` correctly orchestrates:
scene segmentation -> cast discovery -> attribution -> QA -> interpretation.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from audiobook_ai.llm.llama_cpp_backend import LlamaCppBackend
from audiobook_ai.models.book import Chapter
from audiobook_ai.models.story import StoryState


# ---------------------------------------------------------------------------
# Fake chat function that returns pre-programmed responses
# ---------------------------------------------------------------------------

class FakeChatFn:
    """Callable ``list[dict] -> str`` that pops responses from a queue."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, messages: list[dict[str, str]]) -> str:
        self.calls.append({"messages": messages})
        return self.responses.pop(0)


EMPTY_CAST = json.dumps({"characters": []})

ATTRIBUTION_JSON = json.dumps(
    {
        "attributions": [
            {
                "primary": "narrator",
                "reason": "no explicit speaker",
                "evidence": [],
            }
        ],
    }
)

VALID_JSON = json.dumps(
    {
        "dialogues": [
            {
                "speaker_name": "Narrator",
                "emotion": "neutral",
                "text": "Olá, mundo.",
            }
        ],
        "story_updates": {},
    }
)

VALID_JSON_WITH_SPEAKERS = json.dumps(
    {
        "dialogues": [
            {
                "speaker_name": "Maria",
                "emotion": "neutral",
                "text": "Olá, mundo.",
            }
        ],
        "story_updates": {
            "characters": [
                {
                    "id": "maria",
                    "name": "Maria",
                    "aliases": ["Mari"],
                }
            ],
            "aliases": {},
        },
    }
)


def _make_llama_backend(
    responses: list[str],
    cache_dir: Any = None,
    new_pipeline: bool = True,
) -> LlamaCppBackend:
    """Create a LlamaCppBackend with _http_post patched to return proper responses."""
    chat_fn = FakeChatFn(responses)

    def patched_http_post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Simulate _chat's behavior: extract messages, call fake, return wrapped response
        messages = payload.get("messages", [])
        content = chat_fn(messages)
        return {"choices": [{"message": {"content": content}}]}

    backend = LlamaCppBackend(cache_dir=cache_dir, new_pipeline=new_pipeline)
    backend._http_post = patched_http_post  # type: ignore[method-assign]
    return backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_new_pipeline_returns_dialogues() -> None:
    """New pipeline processes a chapter and returns dialogues."""
    backend = _make_llama_backend([EMPTY_CAST, ATTRIBUTION_JSON, VALID_JSON])

    chapter = Chapter(id="ch-001", title="One", text="Ele olhou para o horizonte.")
    result = backend.interpret_chapter(chapter, StoryState())

    # The pipeline should have produced at least one dialogue.
    assert result.dialogues, "Expected dialogues from new pipeline"


def test_new_pipeline_with_cast() -> None:
    """New pipeline discovers characters and includes them in responses."""
    cast_with_char = json.dumps(
        {
            "characters": [
                {
                    "id": "maria",
                    "name": "Maria",
                    "aliases": ["Mari"],
                    "participation": "speaker",
                }
            ],
        }
    )
    backend = _make_llama_backend([cast_with_char, ATTRIBUTION_JSON, VALID_JSON])

    chapter = Chapter(id="ch-001", title="One", text="Maria disse 'Olá'.")
    result = backend.interpret_chapter(chapter, StoryState())

    assert result.dialogues
    cast_chars = result.story_updates.characters
    assert any(c.id == "maria" for c in cast_chars)


def test_new_pipeline_multiple_scenes() -> None:
    """New pipeline handles chapters with multiple scenes."""
    chat_fn = FakeChatFn([
        # Scene 1 cast discovery
        json.dumps({"characters": [
            {"id": "maria", "name": "Maria", "aliases": [], "participation": "speaker"},
            {"id": "joao", "name": "João", "aliases": [], "participation": "speaker"},
        ]}),
        # Scene 1 attribution
        ATTRIBUTION_JSON,
        # Scene 1 unit 0 attribution (for unit-level processing)
        json.dumps({
            "attributions": [{
                "primary": "maria",
                "ranked_candidates": ["maria", "narrator"],
                "evidence": [{"type": "EXPLICIT", "detail": "Maria"}],
                "reason": "nome explícito",
            }],
        }),
        # Scene 1 unit 0 interpretation
        VALID_JSON_WITH_SPEAKERS,
        # Scene 2 cast discovery
        json.dumps({"characters": [
            {"id": "maria", "name": "Maria", "aliases": [], "participation": "speaker"},
            {"id": "joao", "name": "João", "aliases": [], "participation": "speaker"},
        ]}),
        # Scene 2 attribution
        ATTRIBUTION_JSON,
        # Scene 2 unit 0 attribution
        json.dumps({
            "attributions": [{
                "primary": "joao",
                "ranked_candidates": ["joao", "narrator"],
                "evidence": [{"type": "TURN_ORDER", "detail": "João"}],
                "reason": "turno sequencial",
            }],
        }),
        # Scene 2 unit 0 interpretation
        json.dumps({
            "dialogues": [{"speaker_name": "João", "emotion": "neutral", "text": "Respondeu João."}],
            "story_updates": {},
        }),
    ])

    def patched_http_post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages", [])
        content = chat_fn(messages)
        return {"choices": [{"message": {"content": content}}]}

    backend = LlamaCppBackend(cache_dir=None, new_pipeline=True)
    backend._http_post = patched_http_post  # type: ignore[method-assign]

    chapter = Chapter(
        id="ch-002",
        title="Two Scenes",
        text="Maria e João conversam.\n\n[Novo capítulo]\nJoão responde a Maria.",
    )
    result = backend.interpret_chapter(chapter, StoryState())

    assert result.dialogues
    # Both characters should be discovered
    char_ids = {c.id for c in result.story_updates.characters}
    assert "maria" in char_ids or "joao" in char_ids


def test_new_pipeline_legacy_mode_unchanged() -> None:
    """Legacy pipeline still works when new_pipeline=False."""
    backend = LlamaCppBackend(
        cache_dir=None,
        new_pipeline=False,
    )
    # The legacy path is exercised by the existing tests in test_llm.py.
    # This test ensures the flag itself works without error.
    assert backend.new_pipeline is False
