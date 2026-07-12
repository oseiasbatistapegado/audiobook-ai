"""Ollama backend tests with a mock client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from audiobook_ai import config
from audiobook_ai.llm.ollama_backend import LLMInterpretationError, OllamaBackend
from audiobook_ai.models.book import Chapter
from audiobook_ai.models.story import StoryState


class FakeOllamaClient:
    def __init__(self, responses: list[str], *, generate_error: Exception | None = None) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.generate_calls: list[dict[str, Any]] = []
        self.generate_error = generate_error

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        content = self.responses.pop(0)
        return {"message": {"content": content}}

    def generate(self, **kwargs: Any) -> dict[str, Any]:
        self.generate_calls.append(kwargs)
        if self.generate_error is not None:
            raise self.generate_error
        return {}


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


def test_interpret_success() -> None:
    backend = OllamaBackend(client=FakeOllamaClient([VALID_JSON]), cache_dir=None)
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert result.dialogues[0].text == "Olá, mundo."


def test_interpret_retry_then_success() -> None:
    client = FakeOllamaClient(["not-json", VALID_JSON])
    backend = OllamaBackend(client=client, cache_dir=None)
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert len(client.calls) == 2
    assert result.dialogues[0].emotion.value == "neutral"


def test_interpret_fails_after_retry() -> None:
    client = FakeOllamaClient(["bad", "still-bad"])
    backend = OllamaBackend(client=client, cache_dir=None)
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    with pytest.raises(LLMInterpretationError, match="after retry"):
        backend.interpret_chapter(chapter, StoryState())


def test_unload_after_remote_call() -> None:
    client = FakeOllamaClient([VALID_JSON])
    backend = OllamaBackend(client=client, cache_dir=None)
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    backend.interpret_chapter(chapter, StoryState())
    assert backend.last_used_remote is True
    backend.unload()
    assert len(client.generate_calls) == 1
    assert client.generate_calls[0]["model"] == backend.model
    assert client.generate_calls[0]["keep_alive"] == 0


def test_unload_when_model_absent_is_non_fatal() -> None:
    client = FakeOllamaClient([], generate_error=RuntimeError("model not loaded"))
    backend = OllamaBackend(client=client, cache_dir=None)
    backend.unload()  # must not raise
    assert len(client.generate_calls) == 1


def test_cache_hit_does_not_mark_remote(tmp_path: Path) -> None:
    cache = tmp_path / "llm-cache"
    cache.mkdir()
    client = FakeOllamaClient([VALID_JSON])
    backend = OllamaBackend(client=client, cache_dir=cache)
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    backend.interpret_chapter(chapter, StoryState())
    assert backend.last_used_remote is True

    client2 = FakeOllamaClient(["should-not-be-used"])
    backend2 = OllamaBackend(client=client2, cache_dir=cache, model=backend.model)
    backend2.interpret_chapter(chapter, StoryState())
    assert backend2.last_used_remote is False
    assert client2.calls == []


def test_prompt_contains_pt_br_adaptation_policy() -> None:
    backend = OllamaBackend(client=FakeOllamaClient([]), cache_dir=None)
    prompt = backend._load_prompt()
    assert "Brazilian Portuguese" in prompt or "português brasileiro" in prompt.lower()
    assert "pt-BR" in prompt or "Adapt, do not translate literally" in prompt
    assert "dialogues[].text" in prompt


def test_prompt_documents_optional_voice_profile() -> None:
    backend = OllamaBackend(client=FakeOllamaClient([]), cache_dir=None)
    prompt = backend._load_prompt()
    assert "voice_profile" in prompt
    assert "gender" in prompt
    assert "optional" in prompt.lower() or "opcional" in prompt.lower()


def test_interpret_accepts_voice_profile_in_story_updates() -> None:
    payload = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_id": "maria",
                    "speaker_name": "Maria",
                    "emotion": "happy",
                    "text": "Oi!",
                }
            ],
            "story_updates": {
                "characters": [
                    {
                        "id": "maria",
                        "name": "Maria",
                        "aliases": [],
                        "voice_profile": {
                            "gender": "female",
                            "age_range": "adult",
                        },
                    }
                ]
            },
        }
    )
    backend = OllamaBackend(client=FakeOllamaClient([payload]), cache_dir=None)
    chapter = Chapter(id="ch-001", title="One", text="Maria disse oi.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert result.story_updates.characters[0].voice_profile is not None
    assert result.story_updates.characters[0].voice_profile.gender == "female"


def test_cache_hit_when_adaptation_policy_unchanged(tmp_path: Path) -> None:
    cache = tmp_path / "llm-cache"
    cache.mkdir()
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    backend = OllamaBackend(client=FakeOllamaClient([VALID_JSON]), cache_dir=cache)
    backend.interpret_chapter(chapter, StoryState())

    client2 = FakeOllamaClient(["should-not-be-used"])
    backend2 = OllamaBackend(client=client2, cache_dir=cache, model=backend.model)
    result = backend2.interpret_chapter(chapter, StoryState())
    assert client2.calls == []
    assert result.dialogues[0].text == "Olá, mundo."


def test_cache_miss_when_adaptation_policy_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "llm-cache"
    cache.mkdir()
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    backend = OllamaBackend(client=FakeOllamaClient([VALID_JSON]), cache_dir=cache)
    backend.interpret_chapter(chapter, StoryState())

    monkeypatch.setattr(config, "LLM_ADAPTATION_POLICY_VERSION", "v2")
    adapted = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_name": "Narrator",
                    "emotion": "neutral",
                    "text": "Olá de novo.",
                }
            ],
            "story_updates": {},
        }
    )
    client2 = FakeOllamaClient([adapted])
    backend2 = OllamaBackend(client=client2, cache_dir=cache, model=backend.model)
    result = backend2.interpret_chapter(chapter, StoryState())
    assert len(client2.calls) == 1
    assert result.dialogues[0].text == "Olá de novo."
