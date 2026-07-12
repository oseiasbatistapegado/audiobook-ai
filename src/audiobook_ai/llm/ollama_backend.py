"""Ollama LLM backend with JSON validation and a single schema retry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

import ollama
from pydantic import ValidationError

from audiobook_ai import config
from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.models.book import Chapter
from audiobook_ai.models.llm import LLMChapterResponse
from audiobook_ai.models.story import StoryState
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class OllamaClientProtocol(Protocol):
    """Minimal client surface used by ``OllamaBackend`` (mockable)."""

    def chat(self, **kwargs: Any) -> Any: ...

    def generate(self, **kwargs: Any) -> Any: ...

    def generate(self, **kwargs: Any) -> Any: ...


class LLMInterpretationError(RuntimeError):
    """Raised when chapter JSON remains invalid after retry."""


class OllamaBackend(LLMBackend):
    """Call a local Ollama model and validate ``LLMChapterResponse``."""

    def __init__(
        self,
        *,
        model: str = config.DEFAULT_OLLAMA_MODEL,
        host: str = config.DEFAULT_OLLAMA_HOST,
        client: OllamaClientProtocol | None = None,
        cache_dir: Path | None = None,
        prompt_path: Path | None = None,
    ) -> None:
        self.model = model
        self.host = host
        self._client: OllamaClientProtocol = client or ollama.Client(host=host)
        self.cache_dir = cache_dir
        self.prompt_path = prompt_path or (_PROMPTS_DIR / config.LLM_PROMPT_FILE)
        self.last_used_remote = False

    def interpret_chapter(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> LLMChapterResponse:
        """Interpret one chapter with parse → validate → single retry on failure."""
        self.last_used_remote = False
        system_prompt = self._load_prompt()
        user_payload = self._build_user_payload(chapter, story_state)

        cached = self._read_cache(chapter, user_payload)
        if cached is not None:
            logger.info(
                "LLM cache hit chapter=%s backend=ollama model=%s",
                chapter.id,
                self.model,
            )
            return cached

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]

        first = self._chat(messages)
        parsed = self._try_validate(first, chapter_id=chapter.id, attempt=1)
        if parsed is not None:
            self._write_cache(chapter, user_payload, parsed)
            return parsed

        retry_messages = [
            *messages,
            {"role": "assistant", "content": first},
            {
                "role": "user",
                "content": (
                    "Your previous response failed schema validation. "
                    f"Error: {self._last_validation_error}. "
                    "Reply again with JSON only matching the required schema."
                ),
            },
        ]
        second = self._chat(retry_messages)
        parsed = self._try_validate(second, chapter_id=chapter.id, attempt=2)
        if parsed is not None:
            self._write_cache(chapter, user_payload, parsed)
            return parsed

        raise LLMInterpretationError(
            f"Invalid LLM JSON for chapter={chapter.id} backend=ollama "
            f"model={self.model} after retry: {self._last_validation_error}"
        )

    def unload(self) -> None:
        """Ask Ollama to free the model from host/GPU memory (non-fatal)."""
        logger.info("LLM unload backend=ollama model=%s host=%s", self.model, self.host)
        try:
            self._client.generate(model=self.model, prompt="", keep_alive=0)
        except Exception as exc:
            logger.warning(
                "LLM unload failed model=%s host=%s error=%s",
                self.model,
                self.host,
                exc,
            )

    def _load_prompt(self) -> str:
        if not self.prompt_path.is_file():
            raise FileNotFoundError(f"LLM prompt file missing: {self.prompt_path}")
        return self.prompt_path.read_text(encoding="utf-8")

    def _build_user_payload(self, chapter: Chapter, story_state: StoryState) -> str:
        payload = {
            "chapter": chapter.model_dump(),
            "story_state": story_state.model_dump(),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _chat(self, messages: list[dict[str, str]]) -> str:
        logger.info("calling Ollama model=%s host=%s", self.model, self.host)
        response = self._client.chat(model=self.model, messages=messages, format="json")
        self.last_used_remote = True
        content = self._extract_content(response)
        if not content.strip():
            raise LLMInterpretationError(
                f"Empty Ollama response model={self.model} host={self.host}"
            )
        return content

    def _extract_content(self, response: Any) -> str:
        if isinstance(response, dict):
            message = response.get("message") or {}
            return str(message.get("content") or "")
        message = getattr(response, "message", None)
        if message is None:
            return ""
        return str(getattr(message, "content", "") or "")

    def _try_validate(
        self,
        raw: str,
        *,
        chapter_id: str,
        attempt: int,
    ) -> LLMChapterResponse | None:
        self._last_validation_error = ""
        try:
            data = json.loads(self._strip_fences(raw))
            return LLMChapterResponse.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            self._last_validation_error = str(exc)
            logger.warning(
                "LLM schema validation failed chapter=%s attempt=%s error=%s",
                chapter_id,
                attempt,
                exc,
            )
            return None

    def _strip_fences(self, raw: str) -> str:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _adaptation_policy_id(self) -> str:
        """Stable identifier for output locale + adaptation policy (cache key)."""
        return (
            f"output_locale={config.LLM_OUTPUT_LOCALE}"
            f"|adaptation_policy={config.LLM_ADAPTATION_POLICY_VERSION}"
        )

    def _cache_key(self, chapter: Chapter, user_payload: str) -> str:
        digest = hashlib.sha256(
            f"{self.model}\n{chapter.id}\n{self._adaptation_policy_id()}\n{user_payload}".encode(
                "utf-8"
            )
        ).hexdigest()
        return digest

    def _cache_path(self, chapter: Chapter, user_payload: str) -> Path | None:
        if self.cache_dir is None or not config.LLM_CACHE_ENABLED:
            return None
        return self.cache_dir / f"llm-{self._cache_key(chapter, user_payload)}.json"

    def _read_cache(
        self,
        chapter: Chapter,
        user_payload: str,
    ) -> LLMChapterResponse | None:
        path = self._cache_path(chapter, user_payload)
        if path is None or not path.is_file():
            return None
        try:
            return LLMChapterResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError:
            logger.warning("ignoring invalid LLM cache path=%s", path)
            return None

    def _write_cache(
        self,
        chapter: Chapter,
        user_payload: str,
        response: LLMChapterResponse,
    ) -> None:
        path = self._cache_path(chapter, user_payload)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        logger.info("wrote LLM cache path=%s", path)
