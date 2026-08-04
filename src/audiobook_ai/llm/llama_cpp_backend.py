"""llama.cpp (llama-server) LLM backend with cast discovery, unit split, speaker QA, and retries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from audiobook_ai import config
from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.llm.attribution import attribution_scene
from audiobook_ai.llm.cast_fingerprint import story_cast_fingerprint
from audiobook_ai.llm.candidate_generator import generate_candidates
from audiobook_ai.llm.unit_classifier import classify_units
from audiobook_ai.llm.chapter_cast import (
    cast_to_story_updates,
    chapter_cast_fingerprint,
    merge_cast_discoveries,
    restrict_pass2_story_updates,
    speaker_set_from_cast,
)
from audiobook_ai.llm.interpretation_state import InterpretationState
from audiobook_ai.llm.profile_manager import (
    load_character_profiles,
    resolve_character_profile,
    save_character_profiles,
)
from audiobook_ai.llm.sanitize import repair_llm_json_text, sanitize_llm_chapter_payload
from audiobook_ai.llm.scene_graph import SceneGraph, build_scene_graph
from audiobook_ai.llm.scene_segmenter import SceneSegmenter, segment_text
from audiobook_ai.llm.turn_tracker import TurnTracker
from audiobook_ai.llm.speaker_qa import (
    QASeverity,
    SpeakerQAError,
    check_explicit_attribution,
    check_speaker_diarization,
    qa_severity,
    repair_narration_speakers,
    strip_speech_attribution_tags,
)
from audiobook_ai.llm.units import (
    InterpretUnit,
    aggregate_unit_responses,
    split_chapter_text,
)
from audiobook_ai.models.book import Chapter
from audiobook_ai.models.cast import (
    Candidate,
    CharacterProfile,
    DialogueAttribution,
    LLMCastDiscoveryResponse,
    TurnAttribution,
)
from audiobook_ai.models.llm import LLMChapterResponse
from audiobook_ai.models.scene import Scene
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.llm import StoryUpdates
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.story import StoryState
from audiobook_ai.state.voices import apply_story_updates
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class LLMInterpretationError(RuntimeError):
    """Raised when chapter JSON remains invalid after retries."""


class LlamaCppBackend(LLMBackend):
    """Call a local llama-server model and validate ``LLMChapterResponse``."""

    def __init__(
        self,
        *,
        model: str = config.DEFAULT_LLAMA_MODEL,
        host: str = config.DEFAULT_LLAMA_HOST,
        cache_dir: Path | None = None,
        prompt_path: Path | None = None,
        cast_prompt_path: Path | None = None,
        new_pipeline: bool = config.SPEAKER_RESOLUTION_V2_ENABLED,
    ) -> None:
        self.model = model
        self.host = host
        self._base_url = host.rstrip("/")
        self._http_client: httpx.Client | None = None
        self.cache_dir = cache_dir
        self.prompt_path = prompt_path or (_PROMPTS_DIR / config.LLM_PROMPT_FILE)
        self.cast_prompt_path = cast_prompt_path or (
            _PROMPTS_DIR / config.LLM_CAST_DISCOVERY_PROMPT_FILE
        )
        self.new_pipeline = new_pipeline
        self.last_used_remote = False
        self._last_validation_error = ""

    def _ensure_client(self) -> httpx.Client:
        """Lazy-initialize the httpx client (for lifecycle control)."""
        if self._http_client is None:
            self._http_client = httpx.Client(
                base_url=self._base_url,
                timeout=httpx.Timeout(
                    config.LLM_HTTP_TIMEOUT,
                    connect=config.LLM_HTTP_CONNECT_TIMEOUT,
                ),
            )
        return self._http_client

    def _close_client(self) -> None:
        """Close the httpx client (for lifecycle control)."""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def _http_post(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST JSON to an endpoint and return the parsed response body."""
        client = self._ensure_client()
        self.last_used_remote = True
        response = client.post(endpoint, json=payload)
        response.raise_for_status()
        return response.json()

    def interpret_chapter(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> LLMChapterResponse:
        """Pass 1 cast discovery, then Pass 2 interpret units with closed speaker set."""
        self.last_used_remote = False
        if self.new_pipeline:
            return self.interpret_chapter_v2(chapter, story_state)
        working_state = story_state.model_copy(deep=True)

        discovery = self._discover_chapter_cast(chapter, working_state)
        apply_story_updates(working_state, cast_to_story_updates(discovery))
        allowed_speakers = speaker_set_from_cast(discovery.characters)
        cast_fp = chapter_cast_fingerprint(discovery.characters)
        known_ids = {c.id for c in working_state.characters} | {
            e.id for e in discovery.characters
        }

        system_prompt = self._load_prompt(self.prompt_path)
        units = split_chapter_text(chapter.text)
        unit_responses: list[LLMChapterResponse] = []

        for unit in units:
            unit_chapter = Chapter(
                id=chapter.id,
                title=chapter.title,
                text=unit.text,
            )
            response = self._interpret_unit(
                unit_chapter,
                working_state,
                unit=unit,
                system_prompt=system_prompt,
                allowed_speakers=allowed_speakers,
                cast_fingerprint=cast_fp,
                known_ids=known_ids,
            )
            apply_story_updates(working_state, response.story_updates)
            unit_responses.append(response)

        # Surface Pass-1 characters in the aggregated story_updates so callers
        # that only persist the interpret response still see new cast members.
        aggregated = aggregate_unit_responses(unit_responses)
        cast_updates = cast_to_story_updates(discovery)
        if cast_updates.characters:
            merged_chars = {
                c.id: c for c in aggregated.story_updates.characters
            }
            for character in cast_updates.characters:
                if character.id not in merged_chars:
                    merged_chars[character.id] = character
            aggregated = aggregated.model_copy(
                update={
                    "story_updates": aggregated.story_updates.model_copy(
                        update={"characters": list(merged_chars.values())}
                    )
                }
            )
        return aggregated

    def interpret_chapter_v2(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> LLMChapterResponse:
        """New speaker-resolution pipeline: Scene → Cast → Graph → Attri → QA → Interpret.

        When ``SPEAKER_RESOLUTION_V2_ENABLED`` is True (default), this method is
        called by ``interpret_chapter`` instead of the legacy unit-by-unit pipeline.

        Args:
            chapter: The chapter to interpret.
            story_state: The current story state.

        Returns:
            Aggregated ``LLMChapterResponse`` with dialogues and story updates.
        """
        logger.info(
            "LLM interpret chapter=%s backend=llama-cpp model=%s pipeline=v2",
            chapter.id,
            self.model,
        )

        # Phase 0: Scene Segmentation
        segmenter = SceneSegmenter()
        scenes = segmenter.segment(chapter.text)
        if not scenes:
            # Fallback: treat whole chapter as one scene
            scenes = [Scene(scene_id="scene-000", units=[chapter.text], text=chapter.text)]

        # Load character profiles from work dir (persisted across chapters).
        char_profiles_path = (
            self.cache_dir / "character_profiles.json"
            if self.cache_dir
            else None
        )
        profiles: dict[str, CharacterProfile] = (
            load_character_profiles(char_profiles_path)
            if char_profiles_path
            else {}
        )

        state = InterpretationState(scenes=scenes)
        all_dialogues: list[Dialogue] = []
        story_updates_chars: list[Any] = []
        all_allowed_speakers: set[str] = set()

        for scene in scenes:
            # Phase 1: Cast Discovery (per scene, from story_state + existing profiles).
            chapter_cast = self._discover_chapter_cast(chapter, story_state)
            for cast_entry in chapter_cast.characters:
                resolve_character_profile(
                    cast_entry.id,
                    cast_entry.name,
                    cast_entry.aliases,
                    cache=profiles,
                )
            story_updates_chars.extend(cast_entry for cast_entry in chapter_cast.characters)
            all_allowed_speakers.update(
                c.id for c in chapter_cast.characters
            )

        # Save persisted profiles.
        if char_profiles_path:
            save_character_profiles(profiles, char_profiles_path)

        for scene in scenes:
            self._process_scene(
                scene,
                chapter,
                story_state,
                profiles,
                state,
                all_dialogues,
                story_updates_chars,
                all_allowed_speakers,
            )

        # Aggregate and surface cast discovery.
        aggregated = self._aggregate_scene_dialogues(
            all_dialogues,
            story_updates_chars,
            story_state,
            all_allowed_speakers,
        )

        # Save interpretation state for resume.
        if char_profiles_path:
            out_dir = char_profiles_path.parent
            state.save_interpretation_state(out_dir)
            state.write_debug_scene(
                scenes[0].scene_id if scenes else "scene-000", out_dir
            )

        return aggregated

    def _process_scene(
        self,
        scene: Scene,
        chapter: Chapter,
        story_state: StoryState,
        profiles: dict[str, CharacterProfile],
        state: InterpretationState,
        all_dialogues: list[Dialogue],
        story_updates_chars: list[Any],
        all_allowed_speakers: set[str],
    ) -> None:
        """Process a single scene through attribution → QA → interpretation."""
        units = [
            InterpretUnit(index=i, text=u)
            for i, u in enumerate(scene.units)
        ]
        profile_hash = hashlib.sha256(
            json.dumps(
                {cid: cp.model_dump(mode="json") for cid, cp in sorted(profiles.items())},
                sort_keys=True,
            ).encode()
        ).hexdigest()

        # Phase 3: Build scene graph.
        graph = build_scene_graph(scene.units, profiles, [])
        state.scene_graphs[scene.scene_id] = graph

        # Phase 3b: Unit Classification (deterministic, 4 classes).
        unit_classifications = classify_units([u.text for u in units])
        state.unit_classifications[scene.scene_id] = unit_classifications

        # Phase 4: Generate candidates per unit.
        scene_candidates: list[Candidate] = []
        for unit in units:
            candidates = generate_candidates(
                unit.text,
                profiles,
                scene_graph=graph,
            )
            scene_candidates.extend(candidates)

        # Phase 5b: Turn Tracking — deterministic attribution for dialogue units.
        tracker = TurnTracker(
            focus_entity=graph.focus_entity if graph else None,
            scene_graph=graph,
        )
        active_speakers = list({c.speaker_id for c in scene_candidates})
        turn_attributions = tracker.track(
            unit_classifications,
            active_speakers,
            focus_entity=graph.focus_entity if graph else None,
            scene_graph=graph,
        )
        state.turn_attributions[scene.scene_id] = turn_attributions

        # Build resolved map (Turn Attribution → DialogueAttribution).
        resolved_units: list[TurnAttribution] = [
            ta for ta in turn_attributions
            if ta.speaker_id != "narrator"
            or any(
                uc.classification.value in ("narration", "indirect_dialogue")
                for uc in unit_classifications
                if uc.unit_index == ta.unit_index
            )
        ]

        # Phase 5: Attribution via llama-server (only for ambiguous units).
        attributions = attribution_scene(
            units,
            scene_candidates,
            scene=scene,
            character_profiles=profiles,
            unit_classifications=unit_classifications,
            resolved_units=resolved_units,
            character_profiles_hash=profile_hash,
            cache_dir=self.cache_dir,
            _chat_fn=self._chat,
        )
        state.attributions[scene.scene_id] = attributions

        # Phase 6-7: QA per attribution → interpretation per unit.
        for unit_idx, (unit, attribution) in enumerate(zip(units, attributions)):
            severity = qa_severity(attribution.evidence)
            is_rigorous = severity == QASeverity.RIGOROUS

            # Build a minimal chapter-like payload for interpretation.
            unit_chapter = Chapter(
                id=chapter.id,
                title=chapter.title,
                text=unit.text,
            )

            # Attempt interpretation with QA awareness.
            max_retries = (
                config.QA_CORRECTION_MAX_ATTEMPTS
                if is_rigorous
                else 1
            )

            dialogue = self._interpret_scene_unit(
                unit_chapter,
                story_state,
                unit=unit,
                attribution=attribution,
                allowed_speakers=all_allowed_speakers,
                max_retries=max_retries,
                scene_id=scene.scene_id,
                unit_index=unit_idx,
                profiles=profiles,
            )

            all_dialogues.append(dialogue)

    def _interpret_scene_unit(
        self,
        chapter: Chapter,
        story_state: StoryState,
        *,
        unit: InterpretUnit,
        attribution: DialogueAttribution,
        allowed_speakers: set[str],
        max_retries: int,
        scene_id: str,
        unit_index: int,
        profiles: dict[str, CharacterProfile],
    ) -> Dialogue:
        """Interpret a single unit within a scene using attribution guidance."""
        user_payload = json.dumps(
            {
                "scene_id": scene_id,
                "unit_index": unit_index,
                "chapter": chapter.model_dump(),
                "attribution": attribution.model_dump(mode="json"),
                "allowed_speakers": sorted(allowed_speakers),
                "character_profiles": {
                    cid: cp.model_dump(mode="json")
                    for cid, cp in sorted(profiles.items())
                },
            },
            ensure_ascii=False,
            indent=2,
        )

        system_prompt = self._load_prompt(self.prompt_path)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]

        for attempt in range(1, max_retries + 1):
            raw = self._chat(messages)
            if not raw.strip():
                logger.warning(
                    "LLM interpret empty response scene=%s unit=%s attempt=%s",
                    scene_id,
                    unit_index,
                    attempt,
                )
                if attempt >= max_retries:
                    # Fall back to attribution primary speaker.
                    return Dialogue(
                        speaker_id=attribution.primary,
                        speaker_name=None,
                        text=unit.text,
                        emotion=Emotion.NEUTRAL,
                    )
                continue

            parsed = self._try_validate_scene(
                raw,
                chapter_id=chapter.id,
                unit_index=unit_index,
                unit_text=unit.text,
                story_state=story_state,
                attempt=attempt,
                allowed_speakers=allowed_speakers,
            )
            if parsed is not None and parsed.dialogues:
                return parsed.dialogues[0]

            if attempt >= max_retries:
                break

            messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed validation. "
                        "Reply again with JSON only matching the schema."
                    ),
                },
            ]

        # Ultimate fallback: use attribution's primary speaker.
        return Dialogue(
            speaker_id=attribution.primary,
            speaker_name=None,
            text=unit.text,
            emotion=Emotion.NEUTRAL,
        )

    def _aggregate_scene_dialogues(
        self,
        dialogues: list[Dialogue],
        story_updates_chars: list[CharacterProfile],
        story_state: StoryState,
        allowed_speakers: set[str],
    ) -> LLMChapterResponse:
        """Aggregate scene dialogues into a single LLMChapterResponse."""
        from audiobook_ai.models.cast import ChapterCastEntry

        # Build LLMCastDiscoveryResponse from resolved profiles.
        cast_entries: list[ChapterCastEntry] = [
            ChapterCastEntry(
                id=cp.id,  # type: ignore[union-attr]
                name=cp.name,  # type: ignore[union-attr]
                aliases=cp.aliases,  # type: ignore[union-attr]
            )
            for cp in story_updates_chars
            if hasattr(cp, "id") and hasattr(cp, "name") and hasattr(cp, "aliases")
        ]
        discovery = LLMCastDiscoveryResponse(characters=cast_entries)
        cast_updates = cast_to_story_updates(discovery)
        return LLMChapterResponse(
            dialogues=dialogues,
            story_updates=cast_updates,
        )

    def _discover_chapter_cast(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> LLMCastDiscoveryResponse:
        """Pass 1: full chapter when possible; else complete-coverage chunks."""
        cached = self._read_cast_cache(chapter, story_state)
        if cached is not None:
            logger.info(
                "LLM cast cache hit chapter=%s backend=llama-cpp model=%s",
                chapter.id,
                self.model,
            )
            return cached

        chunks = split_chapter_text(
            chapter.text,
            max_chars=config.LLM_CAST_DISCOVERY_MAX_CHARS,
        )
        system_prompt = self._load_prompt(self.cast_prompt_path)
        discoveries: list[LLMCastDiscoveryResponse] = []
        for chunk in chunks:
            chunk_chapter = Chapter(
                id=chapter.id,
                title=chapter.title,
                text=chunk.text,
            )
            discoveries.append(
                self._discover_cast_chunk(
                    chunk_chapter,
                    story_state,
                    system_prompt=system_prompt,
                    chunk_index=chunk.index,
                    chunk_hash=chunk.text_hash,
                )
            )

        merged = merge_cast_discoveries(discoveries)
        self._write_cast_cache(chapter, story_state, merged)
        return merged

    def _discover_cast_chunk(
        self,
        chapter: Chapter,
        story_state: StoryState,
        *,
        system_prompt: str,
        chunk_index: int,
        chunk_hash: str,
    ) -> LLMCastDiscoveryResponse:
        user_payload = self._build_cast_user_payload(chapter, story_state)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]
        max_attempts = config.LLM_CAST_DISCOVERY_MAX_ATTEMPTS

        for attempt in range(1, max_attempts + 1):
            raw = self._chat(messages)
            if not raw.strip():
                self._last_validation_error = (
                    f"empty llama-server response model={self.model} host={self.host}"
                )
                logger.warning(
                    "LLM cast empty response chapter=%s chunk=%s attempt=%s",
                    chapter.id,
                    chunk_index,
                    attempt,
                )
                if attempt >= max_attempts:
                    break
                continue

            parsed = self._try_validate_cast(
                raw,
                chapter_id=chapter.id,
                chunk_index=chunk_index,
                attempt=attempt,
            )
            if parsed is not None:
                return parsed

            if attempt >= max_attempts:
                break

            messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Your previous cast-discovery response failed validation. "
                        f"Error: {self._last_validation_error}. "
                        "Reply again with JSON only matching the cast discovery "
                        "schema (characters with id, name, aliases, participation). "
                        "Do not emit dialogues."
                    ),
                },
            ]

        raise LLMInterpretationError(
            f"Invalid LLM cast JSON for chapter={chapter.id} "
            f"chunk={chunk_index}:{chunk_hash} backend=llama-cpp model={self.model} "
            f"after {max_attempts} attempts: {self._last_validation_error}"
        )

    def _interpret_unit(
        self,
        chapter: Chapter,
        story_state: StoryState,
        *,
        unit: InterpretUnit,
        system_prompt: str,
        allowed_speakers: set[str],
        cast_fingerprint: str,
        known_ids: set[str],
    ) -> LLMChapterResponse:
        user_payload = self._build_user_payload(
            chapter,
            story_state,
            allowed_speakers=allowed_speakers,
        )
        cached = self._read_cache(
            chapter,
            story_state,
            unit=unit,
            cast_fingerprint=cast_fingerprint,
        )
        if cached is not None:
            logger.info(
                "LLM cache hit chapter=%s unit=%s backend=llama-cpp model=%s",
                chapter.id,
                unit.index,
                self.model,
            )
            return cached

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]
        max_attempts = config.LLM_INTERPRET_MAX_ATTEMPTS

        for attempt in range(1, max_attempts + 1):
            raw = self._chat(messages)
            if not raw.strip():
                self._last_validation_error = (
                    f"empty llama-server response model={self.model} host={self.host}"
                )
                logger.warning(
                    "LLM interpret empty response chapter=%s unit=%s attempt=%s",
                    chapter.id,
                    unit.index,
                    attempt,
                )
                if attempt >= max_attempts:
                    break
                continue

            parsed = self._try_validate(
                raw,
                chapter_id=chapter.id,
                unit_index=unit.index,
                unit_text=unit.text,
                story_state=story_state,
                attempt=attempt,
                allowed_speakers=allowed_speakers,
                known_ids=known_ids,
            )
            if parsed is not None:
                self._write_cache(
                    chapter,
                    story_state,
                    parsed,
                    unit=unit,
                    cast_fingerprint=cast_fingerprint,
                )
                return parsed

            if attempt >= max_attempts:
                break

            allowed_list = ", ".join(sorted(allowed_speakers))
            messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed interpretation validation. "
                        f"Error: {self._last_validation_error}. "
                        "Reply again with JSON only matching the required schema. "
                        f"allowed_speakers (closed set): [{allowed_list}]. "
                        "Use narrator only for narration — never as a fallback for "
                        "spoken dialogue. Assign each spoken line to the correct "
                        "allowed speaker; do not invent new speaker ids; "
                        "character text MUST NOT include speech-tags like "
                        "'disse ela' / 'perguntou Horikita'."
                    ),
                },
            ]

        raise LLMInterpretationError(
            f"Invalid LLM JSON for chapter={chapter.id} unit={unit.index} "
            f"backend=llama-cpp model={self.model} after {max_attempts} attempts: "
            f"{self._last_validation_error}"
        )

    def unload(self) -> None:
        """Release resources (close httpx client). The llama-server is stopped by the pipeline."""
        logger.info(
            "LLM unload backend=llama-cpp model=%s host=%s", self.model, self.host
        )
        self._close_client()

    def _load_prompt(self, path: Path | None = None) -> str:
        target = path or self.prompt_path
        if not target.is_file():
            raise FileNotFoundError(f"LLM prompt file missing: {target}")
        return target.read_text(encoding="utf-8")

    def _build_user_payload(
        self,
        chapter: Chapter,
        story_state: StoryState,
        *,
        allowed_speakers: set[str],
    ) -> str:
        payload = {
            "chapter": chapter.model_dump(),
            "story_state": story_state.model_dump(),
            "allowed_speakers": sorted(allowed_speakers),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _build_cast_user_payload(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> str:
        payload = {
            "chapter": chapter.model_dump(),
            "story_state": story_state.model_dump(),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _chat(self, messages: list[dict[str, str]]) -> str:
        logger.info(
            "calling llama-server model=%s host=%s", self.model, self.host
        )
        response_data = self._http_post(
            "/v1/chat/completions",
            {
                "model": self.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "temperature": config.DEFAULT_TEMPERATURE,
            },
        )
        content = self._extract_content(response_data)
        if content.strip():
            return content

        # Thinking models (qwen3/qwen3.6) sometimes leave content empty while
        # still emitting usable JSON in message.thinking — recover before retry.
        thinking = self._extract_thinking(response_data)
        recovered = self._recover_json_from_thinking(thinking)
        if recovered:
            logger.warning(
                "llama-server content empty; recovered JSON from thinking "
                "model=%s host=%s thinking_chars=%s",
                self.model,
                self.host,
                len(thinking),
            )
            return recovered

        # Return empty so cast/interpret loops consume a retry attempt instead
        # of aborting the whole chapter on a single blank response.
        logger.warning(
            "Empty llama-server response model=%s host=%s thinking_chars=%s",
            self.model,
            self.host,
            len(thinking),
        )
        return ""

    def _extract_message_field(self, response: Any, field: str) -> str:
        """Extract a field from the choices array (OpenAI-compatible format)."""
        if isinstance(response, dict):
            choices = response.get("choices")
            if choices and isinstance(choices, list) and choices:
                message = choices[0].get("message") or {}
                if isinstance(message, dict):
                    return str(message.get(field) or "")
        return ""

    def _extract_content(self, response: Any) -> str:
        return self._extract_message_field(response, "content")

    def _extract_thinking(self, response: Any) -> str:
        return self._extract_message_field(response, "thinking")

    @staticmethod
    def _recover_json_from_thinking(thinking: str) -> str:
        text = thinking.strip()
        if not text:
            return ""
        decoder = json.JSONDecoder()
        best = ""
        for index, char in enumerate(text):
            if char != "{":
                continue
            snippet = repair_llm_json_text(text[index:])
            try:
                obj, end = decoder.raw_decode(snippet)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            candidate = snippet[:end]
            if "dialogues" in obj or "characters" in obj or "cast" in obj:
                return candidate
            if len(candidate) > len(best):
                best = candidate
        return best

    def _try_validate_cast(
        self,
        raw: str,
        *,
        chapter_id: str,
        chunk_index: int,
        attempt: int,
    ) -> LLMCastDiscoveryResponse | None:
        self._last_validation_error = ""
        try:
            text = repair_llm_json_text(self._strip_fences(raw))
            data = json.loads(text)
            if isinstance(data, dict) and "characters" not in data:
                data = {"characters": data.get("cast") or []}
            return LLMCastDiscoveryResponse.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            self._last_validation_error = str(exc)
            logger.warning(
                "LLM cast validation failed chapter=%s chunk=%s attempt=%s error=%s",
                chapter_id,
                chunk_index,
                attempt,
                exc,
            )
            return None

    def _try_validate(
        self,
        raw: str,
        *,
        chapter_id: str,
        unit_index: int,
        unit_text: str,
        story_state: StoryState,
        attempt: int,
        allowed_speakers: set[str],
        known_ids: set[str],
    ) -> LLMChapterResponse | None:
        self._last_validation_error = ""
        try:
            text = repair_llm_json_text(self._strip_fences(raw))
            data = json.loads(text)
            data = sanitize_llm_chapter_payload(data)
            parsed = LLMChapterResponse.model_validate(data)
            parsed = parsed.model_copy(
                update={
                    "story_updates": restrict_pass2_story_updates(
                        parsed.story_updates,
                        known_ids=known_ids,
                    )
                }
            )
            parsed = repair_narration_speakers(parsed)
            # Attribution mismatch needs glued tags before option-B strip.
            check_explicit_attribution(parsed, story_state)
            parsed = strip_speech_attribution_tags(parsed)
            check_speaker_diarization(
                parsed,
                unit_text=unit_text,
                story_state=story_state,
                allowed_speakers=allowed_speakers,
            )
            return parsed
        except (json.JSONDecodeError, ValidationError) as exc:
            self._last_validation_error = str(exc)
            logger.warning(
                "LLM validation failed chapter=%s unit=%s attempt=%s error=%s",
                chapter_id,
                unit_index,
                attempt,
                exc,
            )
            return None
        except SpeakerQAError as exc:
            # QA failed but LLM JSON was valid — return needs_review so
            # the pipeline can continue without aborting the chapter.
            logger.info(
                "QA needs_review chapter=%s unit=%s error=%s",
                chapter_id,
                unit_index,
                exc,
            )
            return self._needs_review_response(
                unit_text, str(exc)
            )

    def _try_validate_scene(
        self,
        raw: str,
        *,
        chapter_id: str,
        unit_index: int,
        unit_text: str,
        story_state: StoryState,
        attempt: int,
        allowed_speakers: set[str],
    ) -> LLMChapterResponse | None:
        """Validate a scene-unit LLM response with attribution awareness."""
        self._last_validation_error = ""
        try:
            text = repair_llm_json_text(self._strip_fences(raw))
            data = json.loads(text)
            data = sanitize_llm_chapter_payload(data)
            parsed = LLMChapterResponse.model_validate(data)
            # For scene pipeline, skip explicit attribution checks since
            # attribution was pre-resolved; still enforce diatization.
            parsed = repair_narration_speakers(parsed)
            check_speaker_diarization(
                parsed,
                unit_text=unit_text,
                story_state=story_state,
                allowed_speakers=allowed_speakers,
            )
            return parsed
        except (json.JSONDecodeError, ValidationError) as exc:
            self._last_validation_error = str(exc)
            logger.warning(
                "LLM scene-unit validation failed chapter=%s unit=%s attempt=%s error=%s",
                chapter_id,
                unit_index,
                attempt,
                exc,
            )
            return None
        except SpeakerQAError as exc:
            logger.info(
                "QA needs_review chapter=%s unit=%s error=%s",
                chapter_id,
                unit_index,
                exc,
            )
            return self._needs_review_response(
                unit_text, str(exc)
            )

    def _needs_review_response(
        self,
        unit_text: str,
        reason: str,
    ) -> LLMChapterResponse:
        """Return a Dialogue with status='needs_review' for QA-failed units."""
        dialogue = Dialogue(
            speaker_id=None,
            text=unit_text,
            emotion=Emotion.NEUTRAL,
            status="needs_review",
            rejection_reason=reason,
        )
        return LLMChapterResponse(
            dialogues=[dialogue],
            story_updates=StoryUpdates(
                characters=[],
                aliases={},
            ),
        )

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
        """Stable identifier for locale + adaptation + diarization policy (cache key)."""
        return (
            f"output_locale={config.LLM_OUTPUT_LOCALE}"
            f"|adaptation_policy={config.LLM_ADAPTATION_POLICY_VERSION}"
            f"|diarization_policy={config.LLM_DIARIZATION_POLICY_VERSION}"
        )

    def _cache_key(
        self,
        chapter: Chapter,
        story_state: StoryState,
        *,
        unit: InterpretUnit,
        cast_fingerprint: str,
    ) -> str:
        cast_fp = story_cast_fingerprint(story_state)
        digest = hashlib.sha256(
            (
                f"{self.model}\n{chapter.id}\nunit={unit.index}:{unit.text_hash}\n"
                f"{self._adaptation_policy_id()}\ncast={cast_fp}\n"
                f"chapter_cast={cast_fingerprint}"
            ).encode("utf-8")
        ).hexdigest()
        return digest

    def _cache_path(
        self,
        chapter: Chapter,
        story_state: StoryState,
        *,
        unit: InterpretUnit,
        cast_fingerprint: str,
    ) -> Path | None:
        if self.cache_dir is None or not config.LLM_CACHE_ENABLED:
            return None
        key = self._cache_key(
            chapter,
            story_state,
            unit=unit,
            cast_fingerprint=cast_fingerprint,
        )
        return self.cache_dir / f"llm-{key}.json"

    def _read_cache(
        self,
        chapter: Chapter,
        story_state: StoryState,
        *,
        unit: InterpretUnit,
        cast_fingerprint: str,
    ) -> LLMChapterResponse | None:
        path = self._cache_path(
            chapter,
            story_state,
            unit=unit,
            cast_fingerprint=cast_fingerprint,
        )
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
        story_state: StoryState,
        response: LLMChapterResponse,
        *,
        unit: InterpretUnit,
        cast_fingerprint: str,
    ) -> None:
        path = self._cache_path(
            chapter,
            story_state,
            unit=unit,
            cast_fingerprint=cast_fingerprint,
        )
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        logger.info("wrote LLM cache path=%s", path)

    def _cast_cache_key(self, chapter: Chapter, story_state: StoryState) -> str:
        text_hash = hashlib.sha256(chapter.text.encode("utf-8")).hexdigest()[:16]
        cast_fp = story_cast_fingerprint(story_state)
        digest = hashlib.sha256(
            (
                f"{self.model}\n{chapter.id}\ntext={text_hash}\n"
                f"{self._adaptation_policy_id()}\ncast={cast_fp}"
            ).encode("utf-8")
        ).hexdigest()
        return digest

    def _cast_cache_path(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> Path | None:
        if self.cache_dir is None or not config.LLM_CACHE_ENABLED:
            return None
        return self.cache_dir / f"cast-{self._cast_cache_key(chapter, story_state)}.json"

    def _read_cast_cache(
        self,
        chapter: Chapter,
        story_state: StoryState,
    ) -> LLMCastDiscoveryResponse | None:
        path = self._cast_cache_path(chapter, story_state)
        if path is None or not path.is_file():
            return None
        try:
            return LLMCastDiscoveryResponse.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except ValidationError:
            logger.warning("ignoring invalid cast cache path=%s", path)
            return None

    def _write_cast_cache(
        self,
        chapter: Chapter,
        story_state: StoryState,
        response: LLMCastDiscoveryResponse,
    ) -> None:
        path = self._cast_cache_path(chapter, story_state)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        logger.info("wrote cast cache path=%s", path)
