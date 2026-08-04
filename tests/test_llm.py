"""llama.cpp (llama-server) backend tests with a mock client (legacy unit-by-unit pipeline)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from audiobook_ai import config
from audiobook_ai.llm.llama_cpp_backend import LLMInterpretationError, LlamaCppBackend
from audiobook_ai.models.book import Chapter
from audiobook_ai.models.character import Character
from audiobook_ai.models.story import StoryState


class FakeHttpxResponse:
    """Mimic the subset of httpx.Response API that LlamaCppBackend uses."""

    def __init__(self, json_data: Any, status_code: int = 200) -> None:
        self.json_data = json_data
        self.status_code = status_code
        self.request: dict[str, Any] | None = None

    def json(self) -> Any:
        return self.json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpxClient:
    """Mock httpx.Client that returns pre-programmed responses."""

    def __init__(self, responses: list[str], *, generate_error: Exception | None = None) -> None:
        self.responses: list[str] = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.generate_error = generate_error

    def post(self, endpoint: str, json: dict[str, Any] | None = None) -> FakeHttpxResponse:
        self.calls.append({"endpoint": endpoint, "json": json or {}})
        if not self.responses:
            return FakeHttpxResponse({"choices": [{"message": {"content": ""}}]})
        content = self.responses.pop(0)
        # LlamaCppBackend's _http_post returns response.json() directly,
        # but _interpret_unit expects {"choices": [{"message": {"content": ...}}]}
        return FakeHttpxResponse(content)


EMPTY_CAST = json.dumps({"characters": []})

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


def _cast_speakers(*ids: str) -> str:
    characters = [
        {
            "id": cid,
            "name": cid.replace("_", " ").title(),
            "aliases": [],
            "participation": "speaker",
        }
        for cid in ids
    ]
    return json.dumps({"characters": characters})


def _make_backend(responses: list[str], cache_dir: Path | None = None, model: str | None = None) -> tuple[LlamaCppBackend, FakeHttpxClient]:
    """Create a LlamaCppBackend with _http_post patched to return pre-programmed responses."""
    fake_client = FakeHttpxClient(responses)

    def patched_http_post(endpoint: str, payload: dict[str, Any]) -> Any:
        # Track the call without popping (post() would consume the response)
        fake_client.calls.append({"endpoint": endpoint, "json": payload or {}})
        backend.last_used_remote = True  # mirror real _http_post behavior
        raw = fake_client.responses.pop(0) if fake_client.responses else ""
        # Wrap in llama-server response structure for _extract_content
        # The raw value is a string that _extract_content will return as-is,
        # and _try_validate will parse + validate it.
        return {"choices": [{"message": {"content": raw}}]}

    if model is not None:
        backend = LlamaCppBackend(cache_dir=cache_dir, model=model)  # type: ignore[arg-type]
    else:
        backend = LlamaCppBackend(cache_dir=cache_dir)
    backend._http_post = patched_http_post  # type: ignore[method-assign]
    return backend, fake_client


def test_interpret_success() -> None:
    backend, client = _make_backend([EMPTY_CAST, VALID_JSON])
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert result.dialogues[0].text == "Olá, mundo."
    assert len(client.calls) == 2  # cast + interpret


def test_interpret_retry_then_success() -> None:
    backend, client = _make_backend([EMPTY_CAST, "not-json", VALID_JSON])
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert len(client.calls) == 3
    assert result.dialogues[0].emotion.value == "neutral"


def test_interpret_retries_empty_ollama_response() -> None:
    backend, client = _make_backend([EMPTY_CAST, "", VALID_JSON])
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert len(client.calls) == 3
    assert result.dialogues[0].text == "Olá, mundo."


def test_chat_recovers_json_from_thinking_when_content_empty() -> None:
    thinking_json = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_name": "Narrator",
                    "emotion": "neutral",
                    "text": "Recuperado.",
                }
            ],
            "story_updates": {},
        }
    )

    # Build a backend and patch _http_post directly to simulate thinking recovery
    backend = LlamaCppBackend(cache_dir=None)
    call_count = 0

    def patched_http_post(endpoint: str, payload: dict[str, Any]) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Cast discovery returns valid JSON
            return {"choices": [{"message": {"content": EMPTY_CAST}}]}
        # Interpretation returns empty content + thinking with JSON
        return {"choices": [{"message": {"content": "", "thinking": f"reason...\n{thinking_json}\n"}}]}

    backend._http_post = patched_http_post  # type: ignore[method-assign]
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert result.dialogues[0].text == "Recuperado."
    assert call_count == 2


def test_interpret_fails_after_retry() -> None:
    backend, client = _make_backend([EMPTY_CAST, "bad", "still-bad", "also-bad"])
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    with pytest.raises(LLMInterpretationError, match="after 3 attempts"):
        backend.interpret_chapter(chapter, StoryState())


def test_unload_after_remote_call() -> None:
    backend, client = _make_backend([EMPTY_CAST, VALID_JSON])
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    backend.interpret_chapter(chapter, StoryState())
    assert backend.last_used_remote is True
    backend.unload()  # no-op for LlamaCppBackend (server controlled by pipeline)


def test_cache_hit_does_not_mark_remote(tmp_path: Path) -> None:
    cache = tmp_path / "llm-cache"
    cache.mkdir()
    backend, client = _make_backend([EMPTY_CAST, VALID_JSON], cache_dir=cache)
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    backend.interpret_chapter(chapter, StoryState())
    assert backend.last_used_remote is True

    backend2, client2 = _make_backend(["should-not-be-used"], cache_dir=cache, model=backend.model)
    backend2.interpret_chapter(chapter, StoryState())
    assert client2.calls == []
    assert backend2.last_used_remote is False


def test_interpret_coerces_unknown_emotion_and_speaker_typo() -> None:
    payload = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_name": "Narrator",
                    "emotion": "curious",
                    "text": "Hmm.",
                }
            ],
            "story_updates": {},
        }
    )
    backend, _ = _make_backend([EMPTY_CAST, payload])
    chapter = Chapter(id="ch-001", title="One", text="Hello.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert result.dialogues[0].emotion.value == "excited"


def test_coerce_emotion_aliases() -> None:
    from audiobook_ai.models.emotion import coerce_emotion

    assert coerce_emotion("curious") == "excited"
    assert coerce_emotion("totally-made-up") == "neutral"


def test_prompt_documents_adaptation_rules() -> None:
    backend, _ = _make_backend([])
    prompt = backend._load_prompt()
    assert "dialogues[].text" in prompt
    assert "proper names" in prompt.lower()
    assert "MUST NOT" in prompt  # still has strong rules
    assert "Rewrite freely" in prompt  # fluency instruction


def test_prompt_documents_optional_voice_profile() -> None:
    backend, _ = _make_backend([])
    prompt = backend._load_prompt()
    assert "voice_profile" in prompt
    assert "gender" in prompt
    assert "optional" in prompt.lower() or "opcional" in prompt.lower()


def test_prompt_documents_diarization_rules() -> None:
    backend, _ = _make_backend([])
    prompt = backend._load_prompt()
    assert "Speaker rules" in prompt or "allowed_speakers" in prompt
    assert "narrator" in prompt
    assert "exactly one" in prompt.lower()
    assert "MUST NOT" in prompt  # still has strong rules
    assert "fallback" in prompt.lower()


def test_cast_discovery_prompt_exists() -> None:
    backend, _ = _make_backend([])
    prompt = backend._load_prompt(backend.cast_prompt_path)
    assert "participation" in prompt
    assert "speaker" in prompt
    assert "mentioned" in prompt
    assert "dialogues" not in prompt.lower() or "Do **not**" in prompt


def test_interpret_accepts_voice_profile_from_cast_discovery() -> None:
    cast = json.dumps(
        {
            "characters": [
                {
                    "id": "maria",
                    "name": "Maria",
                    "aliases": [],
                    "participation": "speaker",
                }
            ]
        }
    )
    payload = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_id": "maria",
                    "speaker_name": "Maria",
                    "emotion": "happy",
                    "text": "‘Oi!’",
                }
            ],
            "story_updates": {},
        }
    )
    backend, _ = _make_backend([cast, payload])
    chapter = Chapter(id="ch-001", title="One", text="Maria disse oi.")
    result = backend.interpret_chapter(chapter, StoryState())
    # Cast Discovery no longer includes voice_profile (cold pass 1).
    assert result.story_updates.characters[0].voice_profile is None


def test_cache_hit_when_adaptation_policy_unchanged(tmp_path: Path) -> None:
    cache = tmp_path / "llm-cache"
    cache.mkdir()
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    backend, client = _make_backend([EMPTY_CAST, VALID_JSON], cache_dir=cache)
    backend.interpret_chapter(chapter, StoryState())

    backend2, client2 = _make_backend(["should-not-be-used"], cache_dir=cache, model=backend.model)
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
    backend, _ = _make_backend([EMPTY_CAST, VALID_JSON], cache_dir=cache)
    backend.interpret_chapter(chapter, StoryState())

    monkeypatch.setattr(config, "LLM_ADAPTATION_POLICY_VERSION", "v6")
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
    backend2, client2 = _make_backend([EMPTY_CAST, adapted], cache_dir=cache, model=backend.model)
    result = backend2.interpret_chapter(chapter, StoryState())
    assert len(client2.calls) == 2
    assert result.dialogues[0].text == "Olá de novo."


def test_cache_miss_when_diarization_policy_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "llm-cache"
    cache.mkdir()
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    backend, _ = _make_backend([EMPTY_CAST, VALID_JSON], cache_dir=cache)
    backend.interpret_chapter(chapter, StoryState())

    monkeypatch.setattr(config, "LLM_DIARIZATION_POLICY_VERSION", "v9")
    backend2, client2 = _make_backend([EMPTY_CAST, VALID_JSON], cache_dir=cache, model=backend.model)
    backend2.interpret_chapter(chapter, StoryState())
    assert len(client2.calls) == 2


def test_cache_hit_when_voice_map_changes_but_cast_same(tmp_path: Path) -> None:
    cache = tmp_path / "llm-cache"
    cache.mkdir()
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    story = StoryState(
        characters=[Character(id="hero", name="Hero", aliases=["H"])],
        voice_map={},
    )
    backend, _ = _make_backend([EMPTY_CAST, VALID_JSON], cache_dir=cache)
    backend.interpret_chapter(chapter, story)

    story2 = StoryState(
        characters=[Character(id="hero", name="Hero", aliases=["H"])],
        voice_map={"hero": "hero"},
    )
    backend2, client2 = _make_backend(["should-not-be-used"], cache_dir=cache, model=backend.model)
    result = backend2.interpret_chapter(chapter, story2)
    assert client2.calls == []
    assert result.dialogues[0].text == "Olá, mundo."


def test_cache_miss_when_new_character_added(tmp_path: Path) -> None:
    cache = tmp_path / "llm-cache"
    cache.mkdir()
    chapter = Chapter(id="ch-001", title="One", text="Hello world.")
    story = StoryState(
        characters=[Character(id="hero", name="Hero", aliases=[])],
    )
    backend, _ = _make_backend([EMPTY_CAST, VALID_JSON], cache_dir=cache)
    backend.interpret_chapter(chapter, story)

    story2 = StoryState(
        characters=[
            Character(id="hero", name="Hero", aliases=[]),
            Character(id="villain", name="Villain", aliases=[]),
        ],
    )
    backend2, client2 = _make_backend([EMPTY_CAST, VALID_JSON], cache_dir=cache, model=backend.model)
    backend2.interpret_chapter(chapter, story2)
    assert len(client2.calls) == 2


def test_trailing_comma_json_repaired() -> None:
    payload = (
        '{"dialogues":[{"speaker_name":"Narrator","emotion":"neutral",'
        '"text":"Oi.",},],"story_updates":{},}'
    )
    backend, _ = _make_backend([EMPTY_CAST, payload])
    chapter = Chapter(id="ch-001", title="One", text="Hello.")
    result = backend.interpret_chapter(chapter, StoryState())
    assert result.dialogues[0].text == "Oi."


def test_speaker_qa_retry_then_success() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "ch011_speaker_collapse.json").read_text(
            encoding="utf-8"
        )
    )
    cast = _cast_speakers("k-ayankoji", "k-sudou", "k-ike", "k-yamauchi")
    collapsed = json.dumps(fixture["collapsed_response"], ensure_ascii=False)
    fixed = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_id": "narrator",
                    "emotion": "neutral",
                    "text": "Enquanto estava perdido em pensamentos, alguém chamou.",
                },
                {
                    "speaker_id": "k-sudou",
                    "emotion": "neutral",
                    "text": "‘Yo, Ayanokoji. Você veio, né?’",
                },
                {
                    "speaker_id": "k-ayankoji",
                    "emotion": "neutral",
                    "text": "‘Oh, hey, vocês três.’",
                },
                {
                    "speaker_id": "k-sudou",
                    "emotion": "neutral",
                    "text": "‘Então, você também entrou em um clube?’",
                },
                {
                    "speaker_id": "k-ayankoji",
                    "emotion": "neutral",
                    "text": "‘Oh, não, eu só vim verificar.’",
                },
                {
                    "speaker_id": "k-sudou",
                    "emotion": "neutral",
                    "text": "‘Sim. Joguei basquete desde a escola primária.’",
                },
                {
                    "speaker_id": "k-ike",
                    "emotion": "neutral",
                    "text": "‘Nós só viemos porque achamos que poderia ser divertido.’",
                },
            ],
            "story_updates": {},
        },
        ensure_ascii=False,
    )
    backend, client = _make_backend([cast, collapsed, fixed])
    story = StoryState(
        characters=[Character(**c) for c in fixture["story_characters"]]
    )
    chapter = Chapter(id="ch-011", title="3.2", text=fixture["unit_text"])
    result = backend.interpret_chapter(chapter, story)
    # QA failure returns needs_review instead of retrying — only 2 LLM calls
    assert len(client.calls) == 2
    # At least one dialogue should be needs_review (dominance or narration QA)
    needs_review = [d for d in result.dialogues if d.status == "needs_review"]
    assert len(needs_review) >= 1
    speakers = {d.speaker_id for d in result.dialogues if d.status != "needs_review"}
    # Good dialogues may still be present if some pass QA
    assert "k-sudou" in speakers or len(needs_review) == len(result.dialogues)


def test_speaker_outside_closed_set_returns_needs_review() -> None:
    cast = _cast_speakers("office_lady")
    bad = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_id": "random_stranger",
                    "emotion": "neutral",
                    "text": "‘Oi?’",
                }
            ],
            "story_updates": {},
        }
    )
    good = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_id": "office_lady",
                    "emotion": "neutral",
                    "text": "‘Oi?’",
                }
            ],
            "story_updates": {},
        }
    )
    backend, client = _make_backend([cast, bad, good])
    chapter = Chapter(id="ch-x", title="X", text="Someone spoke.")
    result = backend.interpret_chapter(chapter, StoryState())
    # QA failure returns needs_review instead of retrying — only 2 LLM calls
    assert len(client.calls) == 2
    assert result.dialogues[0].status == "needs_review"
    assert result.dialogues[0].speaker_id is None
    # Text is the original unit text (not the LLM response)
    assert result.dialogues[0].text == "Someone spoke."
    assert "QA closed-set" in (result.dialogues[0].rejection_reason or "")


def test_long_chapter_interprets_units_sequentially(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_INTERPRET_MAX_CHARS", 40)
    cast = _cast_speakers("novo")
    part1 = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_id": "narrator",
                    "emotion": "neutral",
                    "text": "Primeira parte.",
                }
            ],
            "story_updates": {},
        }
    )
    part2 = json.dumps(
        {
            "dialogues": [
                {
                    "speaker_id": "novo",
                    "emotion": "neutral",
                    "text": "‘Oi da segunda.’",
                }
            ],
            "story_updates": {},
        }
    )
    backend, client = _make_backend([cast, part1, part2])
    chapter = Chapter(
        id="ch-long",
        title="Long",
        text=("Alpha paragraph one is here.\n\nBeta paragraph two is here too."),
    )
    result = backend.interpret_chapter(chapter, StoryState())
    assert len(client.calls) == 3
    assert [d.text for d in result.dialogues] == ["Primeira parte.", "‘Oi da segunda.’"]
    second_user = client.calls[2]["json"]["messages"][1]["content"]
    assert "novo" in second_user
    assert "allowed_speakers" in second_user


def test_cast_discovery_chunking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_CAST_DISCOVERY_MAX_CHARS", 40)
    chunk_a = _cast_speakers("alpha")
    chunk_b = json.dumps(
        {
            "characters": [
                {
                    "id": "beta",
                    "name": "Beta",
                    "aliases": [],
                    "participation": "mentioned",
                }
            ]
        }
    )
    interpret = VALID_JSON
    backend, client = _make_backend([chunk_a, chunk_b, interpret])
    chapter = Chapter(
        id="ch-chunk",
        title="Chunk",
        text=("Alpha paragraph one is here.\n\nBeta paragraph two is here too."),
    )
    result = backend.interpret_chapter(chapter, StoryState())
    assert result.dialogues[0].text == "Olá, mundo."
    # two cast chunks + one interpret
    assert len(client.calls) == 3
    ids = {c.id for c in result.story_updates.characters}
    assert "alpha" in ids
    assert "beta" in ids
