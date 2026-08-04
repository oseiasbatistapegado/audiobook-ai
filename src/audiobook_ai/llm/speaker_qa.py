"""Deterministic speaker-diarization QA for LLM chapter responses."""

from __future__ import annotations

import re
from collections import Counter
from enum import Enum
from typing import Any

from audiobook_ai import config
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.llm import LLMChapterResponse
from audiobook_ai.models.story import StoryState

_QUOTE_CHARS = "\"'“”‘’«»「」『』"
_DIALOGUE_DASH_PREFIX = ("—", "–", "－", "- ")
# Unquoted speech heuristics (qwen3:8b often omits quotation marks).
_MAX_UNQUOTED_SPEECH_CHARS = 160
_VOCATIVE = re.compile(
    r"\b[\w'-]+(?:-kun|-san|-chan|-sama|-dono)\b"
    r"|\b(?:você|voce|hey|oi|olá|ola)\b",
    re.IGNORECASE,
)
# Attribution anchored to a named character (not first-person "perguntei"/"respondi").
_SPEECH_VERB = (
    r"(?:disse|respondeu|perguntou|falou|gritou|sussurrou|retrucou|"
    r"exclamou|murmurou|acrescentou|insistiu|rebateu|"
    r"said|asked|replied|answered|shouted|whispered)"
)
_SPEECH_TAG_TARGET = r"(?:ela|ele|[A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)"
_FIRST_PERSON_TAG = r"(?:perguntei|respondi|falei|gritei|sussurrei)"
# Trailing narrative speech-tag glued to character dialogue (option B: drop).
_SPEECH_TAG_SUFFIX = re.compile(
    rf"(?:,\s*|\s+)"
    rf"(?:"
    rf"{_SPEECH_VERB}\s+{_SPEECH_TAG_TARGET}"
    rf"|{_FIRST_PERSON_TAG}"
    rf")"
    rf"(?=\s*[.!]?\s*[\"'”’»」』]?\s*[.!]?\s*$)",
    re.IGNORECASE,
)
_DANGLING_PUNCT_BEFORE_QUOTE = re.compile(r"([?!])\.([\"'”’»」』])")
_COMMA_BEFORE_CLOSE_QUOTE = re.compile(r",(\s*[\"'”’»」』])")

_ATTR_PATTERNS = (
    re.compile(
        r"[\"'“‘«「『].*?[\"'”’»」』]\s*,?\s*"
        r"(?:disse|respondeu|perguntou|falou|gritou|sussurrou|retrucou|"
        r"said|asked|replied|answered|shouted|whispered)\s+"
        r"([A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:disse|respondeu|perguntou|falou|gritou|sussurrou|retrucou|"
        r"said|asked|replied|answered|shouted|whispered)\s+"
        r"([A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)\s+(?:disse|respondeu|perguntou|falou|"
        r"said|asked|replied)\s*:",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÜ][\w'-]+)\s+(?:disse|respondeu|perguntou|falou|"
        r"said|asked|replied)\b",
        re.IGNORECASE,
    ),
)


class SpeakerQAError(ValueError):
    """Speaker diarization quality gate failed."""


def is_quoted_turn(dialogue: Dialogue) -> bool:
    """Return True when the turn uses explicit quote/dash dialogue markers."""
    text = (dialogue.text or "").strip()
    if not text:
        return False
    if text[0] in _QUOTE_CHARS:
        return True
    if text.startswith(_DIALOGUE_DASH_PREFIX):
        return True
    # Opening quote somewhere near the start (after a short lead-in).
    if any(q in text[:40] for q in _QUOTE_CHARS) and sum(
        1 for c in text if c in _QUOTE_CHARS
    ) >= 2:
        return True
    return False


def is_speech_turn(dialogue: Dialogue) -> bool:
    """Return True when the turn is spoken dialogue (quoted or unquoted heuristic).

    qwen3:8b often emits character lines without quotation marks; treat short
    vocatives / questions / exclamations as speech so the narration invariant
    does not false-positive on real dialogue.
    """
    if is_quoted_turn(dialogue):
        return True
    text = (dialogue.text or "").strip()
    if not text or len(text) > _MAX_UNQUOTED_SPEECH_CHARS:
        return False
    if text.endswith(("?", "!")):
        return True
    if _VOCATIVE.search(text):
        return True
    return False


def _speaker_key(dialogue: Dialogue) -> str:
    if dialogue.speaker_id and dialogue.speaker_id.strip():
        return dialogue.speaker_id.strip()
    if dialogue.speaker_name and dialogue.speaker_name.strip():
        return dialogue.speaker_name.strip()
    return ""


def _is_narrator(key: str) -> bool:
    return key.casefold() in {
        "narrator",
        "narrador",
        config.NARRATOR_VOICE_ID.casefold(),
    }


def _story_name_tokens(story_state: StoryState) -> dict[str, str]:
    """Map casefolded display name/alias/id → character_id."""
    mapping: dict[str, str] = {}
    for character in story_state.characters:
        mapping[character.id.casefold()] = character.id
        mapping[character.name.strip().casefold()] = character.id
        # Also map last/first token of multi-word names (Horikita, Suzune).
        parts = [p for p in re.split(r"[\s_]+", character.name.strip()) if p]
        for part in parts:
            if len(part) >= 3:
                mapping[part.casefold()] = character.id
        for alias in character.aliases:
            mapping[alias.strip().casefold()] = character.id
            for part in re.split(r"[\s_]+", alias.strip()):
                if len(part) >= 3:
                    mapping[part.casefold()] = character.id
    return mapping


def _resolve_to_character_id(key: str, name_map: dict[str, str]) -> str | None:
    if not key:
        return None
    if _is_narrator(key):
        return "narrator"
    return name_map.get(key.casefold())


def _evidence_labels(
    unit_text: str,
    story_state: StoryState,
    *,
    dominant_key: str,
) -> set[str]:
    """Distinct speaker evidences in unit_text besides the dominant speaker."""
    found: set[str] = set()
    name_map = _story_name_tokens(story_state)
    dominant_cf = dominant_key.casefold()
    dominant_resolved = _resolve_to_character_id(dominant_key, name_map)
    dominant_ids = {dominant_cf}
    if dominant_resolved:
        dominant_ids.add(dominant_resolved.casefold())
    for label, cid in name_map.items():
        if cid.casefold() in dominant_ids or label in dominant_ids:
            dominant_ids.add(label)
            dominant_ids.add(cid.casefold())

    text_cf = unit_text.casefold()
    for label, cid in name_map.items():
        if not label or label in dominant_ids:
            continue
        if label in text_cf:
            found.add(cid)

    for pattern in _ATTR_PATTERNS:
        for match in pattern.finditer(unit_text):
            name = match.group(1).strip()
            key = name.casefold()
            if key in dominant_ids or _is_narrator(key):
                continue
            resolved = name_map.get(key)
            if resolved is None:
                continue
            if resolved.casefold() in dominant_ids:
                continue
            found.add(resolved)

    return found


def repair_narration_speakers(response: LLMChapterResponse) -> LLMChapterResponse:
    """Coerce non-speech turns to ``narrator`` (deterministic; 8b often tags POV)."""
    repaired: list[Dialogue] = []
    changed = False
    for dialogue in response.dialogues:
        key = _speaker_key(dialogue)
        if is_speech_turn(dialogue) or not key or _is_narrator(key):
            repaired.append(dialogue)
            continue
        changed = True
        repaired.append(
            dialogue.model_copy(
                update={"speaker_id": "narrator", "speaker_name": None}
            )
        )
    if not changed:
        return response
    return response.model_copy(update={"dialogues": repaired})


def has_speech_attribution_tag(text: str) -> bool:
    """Return True when ``text`` ends with a narrative speech-tag suffix."""
    return bool(_SPEECH_TAG_SUFFIX.search(text or ""))


def _strip_one_speech_tag(text: str) -> str:
    stripped = _SPEECH_TAG_SUFFIX.sub("", text)
    if stripped == text:
        return text
    stripped = _COMMA_BEFORE_CLOSE_QUOTE.sub(r"\1", stripped)
    stripped = _DANGLING_PUNCT_BEFORE_QUOTE.sub(r"\1\2", stripped)
    return stripped.strip()


def _is_empty_spoken_text(text: str) -> bool:
    """True when only quotes/punctuation remain (no spoken words)."""
    core = re.sub(r"[\"'“”‘’«»「」『』]", "", text or "")
    core = re.sub(r"[.!?,;:\s]+", "", core)
    return not core


def strip_speech_attribution_tags(response: LLMChapterResponse) -> LLMChapterResponse:
    """Drop trailing ``disse ela`` / ``perguntou X`` tags from character turns.

    Narrator turns are left unchanged. Empty text after strip raises
    ``SpeakerQAError`` so the interpret attempt fails (retry), not succeeds.
    """
    repaired: list[Dialogue] = []
    changed = False
    for index, dialogue in enumerate(response.dialogues):
        key = _speaker_key(dialogue)
        if _is_narrator(key):
            repaired.append(dialogue)
            continue
        original = dialogue.text or ""
        stripped = _strip_one_speech_tag(original)
        if stripped == original:
            repaired.append(dialogue)
            continue
        changed = True
        if _is_empty_spoken_text(stripped):
            raise SpeakerQAError(
                "speaker QA speech-tag: empty text after strip "
                f"index={index} (original={original[:80]!r})"
            )
        repaired.append(dialogue.model_copy(update={"text": stripped}))
    if not changed:
        return response
    return response.model_copy(update={"dialogues": repaired})


def _check_narration(response: LLMChapterResponse) -> None:
    for index, dialogue in enumerate(response.dialogues):
        if is_speech_turn(dialogue):
            continue
        key = _speaker_key(dialogue)
        if not key or _is_narrator(key):
            continue
        raise SpeakerQAError(
            "speaker QA narration: non-speech turn "
            f"index={index} speaker={key!r} must be narrator "
            f"(text={dialogue.text[:80]!r})"
        )


def _check_speech_tags(response: LLMChapterResponse) -> None:
    """Reject character turns that still carry narrative speech-tag suffixes."""
    for index, dialogue in enumerate(response.dialogues):
        key = _speaker_key(dialogue)
        if not key or _is_narrator(key):
            continue
        text = dialogue.text or ""
        if not has_speech_attribution_tag(text):
            continue
        raise SpeakerQAError(
            "speaker QA speech-tag: character turn "
            f"index={index} speaker={key!r} still has attribution tag "
            f"(text={text[:100]!r})"
        )


def check_explicit_attribution(
    response: LLMChapterResponse,
    story_state: StoryState,
) -> None:
    """Fail when a named speech-tag conflicts with the turn speaker.

    Callers SHOULD run this on the pre-strip response so glued tags like
    ``perguntou Horikita`` still provide a mismatch signal before option-B
    strip discards them.
    """
    name_map = _story_name_tokens(story_state)
    for index, dialogue in enumerate(response.dialogues):
        text = dialogue.text or ""
        speaker_key = _speaker_key(dialogue)
        speaker_id = _resolve_to_character_id(speaker_key, name_map)
        # If speaker is unknown id not in story, still compare on raw key.
        speaker_norm = (speaker_id or speaker_key).casefold() if speaker_key else ""

        attributed: set[str] = set()
        for pattern in _ATTR_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1).strip()
                resolved = _resolve_to_character_id(name, name_map)
                if resolved is None or _is_narrator(resolved):
                    continue
                attributed.add(resolved)

        if not attributed:
            continue

        for cid in attributed:
            if cid.casefold() == speaker_norm:
                continue
            # Also allow speaker_key raw match to attributed name tokens.
            if speaker_key and cid.casefold() == speaker_key.casefold():
                continue
            raise SpeakerQAError(
                "speaker QA attribution: turn "
                f"index={index} speaker={speaker_key!r} conflicts with "
                f"explicit attribution to {cid!r} (text={text[:100]!r})"
            )


def _check_dominance(
    response: LLMChapterResponse,
    *,
    unit_text: str,
    story_state: StoryState,
    min_quoted_turns: int,
    dominance_threshold: float,
) -> None:
    quoted = [d for d in response.dialogues if is_speech_turn(d)]
    quoted_turns = len(quoted)
    if quoted_turns < min_quoted_turns:
        return

    keys = [_speaker_key(d) for d in quoted]
    keys = [k for k in keys if k]
    if not keys:
        return

    non_narrator = [k for k in keys if not _is_narrator(k)]
    if not non_narrator:
        return

    counts = Counter(non_narrator)
    dominant_key, dominant_count = counts.most_common(1)[0]
    dominant_ratio = dominant_count / quoted_turns
    if dominant_ratio < dominance_threshold:
        return

    evidence = _evidence_labels(
        unit_text,
        story_state,
        dominant_key=dominant_key,
    )
    if len(evidence) < 2:
        return

    raise SpeakerQAError(
        "speaker QA dominance: quoted_turns="
        f"{quoted_turns} dominant_speaker={dominant_key!r} "
        f"dominant_ratio={dominant_ratio:.2f} "
        f"evidence_of_multiple_speakers={sorted(evidence)}"
    )


def check_speakers_in_allowed_set(
    response: LLMChapterResponse,
    *,
    allowed_speakers: set[str],
    story_state: StoryState,
) -> None:
    """Fail when any dialogue speaker is outside the closed speaker set."""
    name_map = _story_name_tokens(story_state)
    allowed_cf = {s.casefold() for s in allowed_speakers if s}
    # Always accept narrator aliases even if caller omitted a spelling.
    allowed_cf.update({"narrator", "narrador", config.NARRATOR_VOICE_ID.casefold()})

    for index, dialogue in enumerate(response.dialogues):
        key = _speaker_key(dialogue)
        if not key:
            raise SpeakerQAError(
                f"speaker QA closed-set: turn index={index} missing speaker"
            )
        if _is_narrator(key):
            continue
        resolved = _resolve_to_character_id(key, name_map) or key
        if resolved.casefold() in allowed_cf or key.casefold() in allowed_cf:
            continue
        raise SpeakerQAError(
            "speaker QA closed-set: turn "
            f"index={index} speaker={key!r} not in allowed_speakers="
            f"{sorted(allowed_speakers)}"
        )


def _check_narrator_collapse(
    response: LLMChapterResponse,
    *,
    unit_text: str,
    story_state: StoryState,
    allowed_speakers: set[str] | None,
    min_speech_turns: int,
    collapse_threshold: float,
) -> None:
    """Reject dialogue-heavy units collapsed onto narrator despite multi-speaker cast."""
    speech = [d for d in response.dialogues if is_speech_turn(d)]
    speech_turns = len(speech)
    if speech_turns < min_speech_turns:
        return

    candidates: set[str] = set()
    if allowed_speakers:
        candidates = {
            s for s in allowed_speakers if s and not _is_narrator(s)
        }
    if len(candidates) < 2:
        # Fall back to story ids + textual evidence of other speakers.
        for character in story_state.characters:
            candidates.add(character.id)
        evidence = _evidence_labels(
            unit_text,
            story_state,
            dominant_key="narrator",
        )
        candidates.update(evidence)
        candidates = {c for c in candidates if c and not _is_narrator(c)}

    if len(candidates) < 2:
        return

    narrator_count = sum(
        1 for d in speech if _is_narrator(_speaker_key(d))
    )
    ratio = narrator_count / speech_turns
    if ratio < collapse_threshold:
        return

    raise SpeakerQAError(
        "speaker QA narrator-collapse: speech_turns="
        f"{speech_turns} narrator_speech_ratio={ratio:.2f} "
        f"candidate_speakers={sorted(candidates)}"
    )


def check_speaker_diarization(
    response: LLMChapterResponse,
    *,
    unit_text: str,
    story_state: StoryState,
    min_quoted_turns: int | None = None,
    dominance_threshold: float | None = None,
    allowed_speakers: set[str] | None = None,
    min_narrator_collapse_speech_turns: int | None = None,
    narrator_collapse_threshold: float | None = None,
) -> None:
    """Raise ``SpeakerQAError`` when any speaker invariant fails.

    Invariants (OR): closed-set (when provided), narration, speech-tag,
    explicit attribution, dominance, narrator-collapse.
    Does not evaluate PT-BR adaptation quality.
    Callers SHOULD run ``repair_narration_speakers`` and
    ``strip_speech_attribution_tags`` before this gate.
    """
    min_quoted = (
        config.LLM_SPEAKER_QA_MIN_QUOTED_TURNS
        if min_quoted_turns is None
        else min_quoted_turns
    )
    threshold = (
        config.LLM_SPEAKER_QA_DOMINANCE_THRESHOLD
        if dominance_threshold is None
        else dominance_threshold
    )
    min_collapse = (
        config.LLM_SPEAKER_QA_NARRATOR_COLLAPSE_MIN_SPEECH_TURNS
        if min_narrator_collapse_speech_turns is None
        else min_narrator_collapse_speech_turns
    )
    collapse_threshold = (
        config.LLM_SPEAKER_QA_NARRATOR_COLLAPSE_THRESHOLD
        if narrator_collapse_threshold is None
        else narrator_collapse_threshold
    )

    if allowed_speakers is not None:
        check_speakers_in_allowed_set(
            response,
            allowed_speakers=allowed_speakers,
            story_state=story_state,
        )
    _check_narration(response)
    check_explicit_attribution(response, story_state)
    _check_speech_tags(response)
    _check_dominance(
        response,
        unit_text=unit_text,
        story_state=story_state,
        min_quoted_turns=min_quoted,
        dominance_threshold=threshold,
    )
    _check_narrator_collapse(
        response,
        unit_text=unit_text,
        story_state=story_state,
        allowed_speakers=allowed_speakers,
        min_speech_turns=min_collapse,
        collapse_threshold=collapse_threshold,
    )


class QASeverity(str, Enum):
    """Severity levels for speaker attribution QA."""

    SKIP = "skip"          # No QA needed (explicit evidence)
    MODERATE = "moderate"  # Basic validation
    RIGOROUS = "rigorous"  # Full validation with retry


def check_speaker_diarization_scene(
    attributions: list[Any],
    active_speakers: list[str],
    *,
    allowed_ids: list[str] | None = None,
    narrator_collapse_threshold: float = 0.7,
) -> QASeverity:
    """Scene-level QA for speaker diatization.

    Checks:
        - Narrator collapse: if > threshold of dialogue units assigned to narrator
        - Alternation: if 2+ active speakers but only 1 appears in attributions
        - Closed-set: all assigned speakers must be in allowed_ids

    Args:
        attributions: List of DialogueAttribution (from Turn Tracker + LLM).
        active_speakers: List of known character speaker_ids.
        allowed_ids: Optional override for the allowed speaker set.
        narrator_collapse_threshold: Ratio threshold for narrator collapse.

    Returns:
        The QA severity level for the scene.
    """
    if not attributions:
        return QASeverity.SKIP

    allowed = allowed_ids or [*active_speakers, "narrator"]
    speakers_used: set[str] = set()

    for attr in attributions:
        sid = attr.primary if hasattr(attr, "primary") else attr.get("primary", "")
        speakers_used.add(sid)

    # Check 1: Closed-set validation.
    for sid in speakers_used:
        if sid not in allowed:
            return QASeverity.RIGOROUS

    # Check 2: Narrator collapse — only meaningful when there are active speakers.
    dialogue_attributions = [
        a for a in attributions
        if hasattr(a, "primary") and a.primary != "narrator"
    ]
    narrator_attributions = [
        a for a in attributions
        if hasattr(a, "primary") and a.primary == "narrator"
    ]
    total_dialogue = len(dialogue_attributions) + len(narrator_attributions)
    if total_dialogue > 0 and active_speakers:
        narrator_ratio = len(narrator_attributions) / total_dialogue
        if narrator_ratio > narrator_collapse_threshold:
            return QASeverity.RIGOROUS

    # Check 3: Alternation — 2+ active speakers but only 1 used.
    dialogue_speakers = speakers_used - {"narrator"}
    if len(active_speakers) >= 2 and len(dialogue_speakers) == 1:
        return QASeverity.MODERATE

    return QASeverity.SKIP


def qa_severity(evidence: list[Any]) -> QASeverity:
    """Determine QA severity based on evidence types.

    Mapping:
        EXPLICIT → skip
        TURN_ORDER → moderate
        SCENE_CONTEXT → moderate
        ALIAS_MATCH → moderate
        EMBEDDING → rigorous if gap ≤ 0.20
        RELATIONSHIP → moderate

    Args:
        evidence: List of evidence entries from attribution.

    Returns:
        The appropriate QA severity level.
    """
    if not evidence:
        return QASeverity.MODERATE  # Default: moderate

    types = {e.type if hasattr(e, "type") else e.get("type") for e in evidence}

    # EXPLICIT always skips QA — the attribution is clear.
    # TURN_TRACKER is deterministic (code-based), no LLM involved → skip.
    # FIRST_PERSON is also deterministic (regex marker) → skip.
    if "EXPLICIT" in types or "TURN_TRACKER" in types or "FIRST_PERSON" in types:
        return QASeverity.SKIP

    # EMBEDDING → rigorous if gap ≤ 0.20 (low similarity = high uncertainty).
    if "EMBEDDING" in types:
        for entry in evidence:
            detail = entry.detail if hasattr(entry, "detail") else entry.get("detail", "")
            if "embedding_similarity" in detail:
                try:
                    gap = float(detail.split(":")[1])
                    if gap <= config.ATTRIBUTION_EMBEDDING_GAP_THRESHOLD:
                        return QASeverity.RIGOROUS
                except (ValueError, IndexError):
                    pass
        # EMBEDDING with good similarity → moderate.
        return QASeverity.MODERATE

    # RELATIONSHIP → moderate.
    if "RELATIONSHIP" in types:
        return QASeverity.MODERATE

    # TURN_ORDER, SCENE_CONTEXT, ALIAS_MATCH → moderate.
    if types & {"TURN_ORDER", "SCENE_CONTEXT", "ALIAS_MATCH"}:
        return QASeverity.MODERATE

    # Unknown evidence type → moderate.
    return QASeverity.MODERATE
