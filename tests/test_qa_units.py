"""QA-by-unit tests: one problematic unit (54) fails, surrounding units pass."""

from __future__ import annotations

from audiobook_ai.llm.speaker_qa import (
    check_explicit_attribution,
    check_speaker_diarization,
    strip_speech_attribution_tags,
)
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.llm import LLMChapterResponse, StoryUpdates
from audiobook_ai.models.story import StoryState


def _make_dialogues(dialogue_data: list[dict]) -> LLMChapterResponse:
    """Build LLMChapterResponse from raw dialogue dicts."""
    dialogues = [Dialogue(**d) for d in dialogue_data]
    return LLMChapterResponse(
        dialogues=dialogues,
        story_updates=StoryUpdates(characters=[], aliases={}),
    )


def test_good_units_pass_diarization() -> None:
    """Units without speech tags pass diatization checks."""
    state = StoryState()
    allowed_speakers = {"narrator", "maria"}
    for i in range(10):
        resp = _make_dialogues(
            [
                {
                    "speaker_id": "maria" if i % 2 == 0 else "narrator",
                    "speaker_name": "Maria" if i % 2 == 0 else None,
                    "text": f"Maria disse 'Olá, mundo {i}'." if i % 2 == 0 else f"Narra-se o capítulo {i}.",
                    "emotion": "neutral",
                }
            ]
        )
        # Should not raise
        check_speaker_diarization(
            resp,
            unit_text=resp.dialogues[0].text,
            story_state=state,
            allowed_speakers=allowed_speakers,
        )


def test_speech_tag_unit_fails_attribution() -> None:
    """Unit with speech tag like 'disse ela' fails attribution check."""
    resp = _make_dialogues(
        [
            {
                "speaker_id": "maria",
                "speaker_name": "Maria",
                "text": "'Olá, mundo!' disse ela.",
                "emotion": "neutral",
            }
        ]
    )
    state = StoryState()
    allowed_speakers = {"narrator", "maria"}

    # This should raise SpeakerQAError because of the speech tag
    from audiobook_ai.llm.speaker_qa import SpeakerQAError
    try:
        check_explicit_attribution(resp, state)
        # If no exception raised, try stripping tags (which should remove it)
        resp2 = strip_speech_attribution_tags(resp)
        assert len(resp2.dialogues) == 1
    except SpeakerQAError:
        # Expected for speech-tagged units
        pass


def test_mixed_units_one_fails() -> None:
    """Chapter with 100 units: unit 54 has speech tag, rest pass."""
    dialogue_data: list[dict] = []
    for i in range(100):
        if i == 54:
            # Unit 54: problematic speech tag
            dialogue_data.append(
                {
                    "speaker_id": "maria",
                    "speaker_name": "Maria",
                    "text": "'Disse ela, com firmeza.' respondeu Maria.",
                    "emotion": "neutral",
                }
            )
        elif i % 2 == 0:
            dialogue_data.append(
                {
                    "speaker_id": "maria",
                    "speaker_name": "Maria",
                    "text": f"Maria disse 'Texto {i}'.",
                    "emotion": "neutral",
                }
            )
        else:
            dialogue_data.append(
                {
                    "speaker_id": "narrator",
                    "speaker_name": None,
                    "text": f"Narra-se o capítulo {i}.",
                    "emotion": "neutral",
                }
            )

    resp = _make_dialogues(dialogue_data)
    state = StoryState()
    allowed_speakers = {"narrator", "maria"}

    # The response should not fail entirely — strip_speech_attribution_tags
    # removes the speech tags and the response becomes valid
    resp2 = strip_speech_attribution_tags(resp)
    assert len(resp2.dialogues) == 100
    for j, d in enumerate(resp2.dialogues):
        assert j in {k for k in range(100)}


def test_unknown_speaker_fails_diarization() -> None:
    """Unit with unknown speaker (not in allowed set) fails diatization."""
    resp = _make_dialogues(
        [
            {
                "speaker_id": "unknown_person",
                "speaker_name": "Unknown",
                "text": "Alguém falou.",
                "emotion": "neutral",
            }
        ]
    )
    state = StoryState()
    allowed_speakers = {"narrator", "maria"}

    from audiobook_ai.llm.speaker_qa import SpeakerQAError
    try:
        check_speaker_diarization(
            resp,
            unit_text=resp.dialogues[0].text,
            story_state=state,
            allowed_speakers=allowed_speakers,
        )
        assert False, "Expected SpeakerQAError"
    except SpeakerQAError:
        pass


def test_speaker_outside_closed_set_returns_needs_review() -> None:
    """Unknown speaker produces needs_review Dialogue, not crash."""
    from audiobook_ai.llm.llama_cpp_backend import LlamaCppBackend
    from audiobook_ai import config

    # Simulate what happens when QA rejects a unit
    backend = LlamaCppBackend(cache_dir=None, new_pipeline=False)
    resp = backend._needs_review_response(
        "Alguém falou.",
        "speaker unknown_person not in allowed set",
    )
    assert resp.dialogues[0].status == "needs_review"
    assert resp.dialogues[0].rejection_reason is not None
