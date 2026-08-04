"""Tests for deterministic speaker diarization QA."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiobook_ai.llm.speaker_qa import SpeakerQAError, check_speaker_diarization
from audiobook_ai.models.character import Character
from audiobook_ai.models.dialogue import Dialogue
from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.llm import LLMChapterResponse
from audiobook_ai.models.story import StoryState

_FIXTURES = Path(__file__).parent / "fixtures"
_CH011 = _FIXTURES / "ch011_speaker_collapse.json"
_CH004 = _FIXTURES / "ch004_speaker_local_errors.json"
_CH005 = _FIXTURES / "ch005_narrator_collapse.json"


def _story_from_fixture(data: dict) -> StoryState:
    return StoryState(
        characters=[Character(**c) for c in data["story_characters"]],
    )


def test_ch011_fixture_rejects_collapse() -> None:
    from audiobook_ai.llm.speaker_qa import strip_speech_attribution_tags

    data = json.loads(_CH011.read_text(encoding="utf-8"))
    response = LLMChapterResponse.model_validate(data["collapsed_response"])
    story = _story_from_fixture(data)
    stripped = strip_speech_attribution_tags(response)
    with pytest.raises(SpeakerQAError, match="speaker QA (dominance|narration|attribution)"):
        check_speaker_diarization(
            stripped,
            unit_text=data["unit_text"],
            story_state=story,
        )


def test_ch004_fixture_rejects_local_errors_with_low_dominance() -> None:
    data = json.loads(_CH004.read_text(encoding="utf-8"))
    response = LLMChapterResponse.model_validate(data["collapsed_response"])
    story = _story_from_fixture(data)
    quoted = [
        d
        for d in response.dialogues
        if (d.text or "").lstrip()[:1] in "\"'“‘«"
    ]
    # Dominance must stay below product threshold so failure is local.
    from collections import Counter

    from audiobook_ai.llm.speaker_qa import is_quoted_turn

    q = [d for d in response.dialogues if is_quoted_turn(d)]
    counts = Counter(d.speaker_id for d in q if d.speaker_id and d.speaker_id != "narrator")
    dom_n = counts.most_common(1)[0][1]
    assert dom_n / len(q) < 0.85

    with pytest.raises(SpeakerQAError, match="speaker QA (narration|attribution)"):
        check_speaker_diarization(
            response,
            unit_text=data["unit_text"],
            story_state=story,
        )


def test_monologue_passes_speaker_qa() -> None:
    response = LLMChapterResponse(
        dialogues=[
            Dialogue(speaker_id="narrator", emotion=Emotion.NEUTRAL, text="Eu caminhei."),
            Dialogue(
                speaker_id="k-ayankoji",
                emotion=Emotion.NEUTRAL,
                text="‘Estou sozinho aqui.’",
            ),
        ]
    )
    story = StoryState(
        characters=[Character(id="k-ayankoji", name="Ayanokoji", aliases=[])]
    )
    check_speaker_diarization(
        response,
        unit_text="Eu caminhei sozinho. Ninguém mais falou.",
        story_state=story,
    )


def test_ch005_fixture_rejects_narrator_collapse() -> None:
    data = json.loads(_CH005.read_text(encoding="utf-8"))
    response = LLMChapterResponse.model_validate(data["collapsed_response"])
    story = _story_from_fixture(data)
    with pytest.raises(SpeakerQAError, match="speaker QA narrator-collapse"):
        check_speaker_diarization(
            response,
            unit_text=data["unit_text"],
            story_state=story,
            allowed_speakers=set(data["allowed_speakers"]),
        )


def test_closed_set_rejects_unknown_speaker() -> None:
    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="stranger",
                emotion=Emotion.NEUTRAL,
                text="‘Oi?’",
            )
        ]
    )
    story = StoryState(
        characters=[Character(id="office_lady", name="OL", aliases=[])]
    )
    with pytest.raises(SpeakerQAError, match="speaker QA closed-set"):
        check_speaker_diarization(
            response,
            unit_text="Someone spoke.",
            story_state=story,
            allowed_speakers={"narrator", "office_lady"},
        )


def test_unquoted_dialogue_question_is_speech_not_narration() -> None:
    """qwen3:8b often omits quotes; short questions must not force narrator."""
    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="suzune_horikita",
                emotion=Emotion.NEUTRAL,
                text="Ayanokouji-kun, você tem um momento?",
            ),
            Dialogue(
                speaker_id="narrator",
                emotion=Emotion.NEUTRAL,
                text=(
                    "Mesmo com os olhos fechados, eu entendia. Podia sentir a "
                    "presença da diabólica e bela mulher ao meu lado."
                ),
            ),
        ]
    )
    story = StoryState(
        characters=[
            Character(id="suzune_horikita", name="Horikita", aliases=[]),
            Character(id="kiyotaka_ayanokoji", name="Ayanokoji", aliases=[]),
        ]
    )
    check_speaker_diarization(
        response,
        unit_text="Horikita chamou Ayanokoji.",
        story_state=story,
    )


def test_long_prose_on_pov_still_fails_narration() -> None:
    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="kiyotaka_ayanokoji",
                emotion=Emotion.NEUTRAL,
                text=(
                    "Meu cérebro, parecido com um computador, executou "
                    "instantaneamente todos os cálculos para chegar à resposta."
                ),
            ),
        ]
    )
    story = StoryState(
        characters=[Character(id="kiyotaka_ayanokoji", name="Ayanokoji", aliases=[])]
    )
    with pytest.raises(SpeakerQAError, match="speaker QA narration"):
        check_speaker_diarization(
            response,
            unit_text="prose",
            story_state=story,
        )


def test_repair_narration_coerces_prose_to_narrator() -> None:
    from audiobook_ai.llm.speaker_qa import repair_narration_speakers

    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="kayotaka_ayanokoji",
                emotion=Emotion.NEUTRAL,
                text=(
                    "Mesmo com os olhos fechados, eu entendi. Podia sentir a "
                    "presença do diabo enquanto ela falava."
                ),
            ),
            Dialogue(
                speaker_id="suzune_horikita",
                emotion=Emotion.NEUTRAL,
                text="Ayanokouji-kun, você tem um momento?",
            ),
        ]
    )
    repaired = repair_narration_speakers(response)
    assert repaired.dialogues[0].speaker_id == "narrator"
    assert repaired.dialogues[1].speaker_id == "suzune_horikita"
    story = StoryState(
        characters=[
            Character(id="suzune_horikita", name="Horikita", aliases=[]),
            Character(id="kiyotaka_ayanokoji", name="Ayanokoji", aliases=[]),
        ]
    )
    check_speaker_diarization(
        repaired,
        unit_text="Horikita chamou.",
        story_state=story,
    )


def test_aligned_attribution_passes() -> None:
    """Named tags aligned to speaker: strip first, then QA on clean speech."""
    from audiobook_ai.llm.speaker_qa import strip_speech_attribution_tags

    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="suzune_horikita",
                emotion=Emotion.NEUTRAL,
                text="‘Veja, você está acordado.’ perguntou Horikita.",
            ),
            Dialogue(
                speaker_id="kiyotaka_ayanokoji",
                emotion=Emotion.NEUTRAL,
                text="‘O que?’ perguntei.",
            ),
        ]
    )
    story = StoryState(
        characters=[
            Character(
                id="kiyotaka_ayanokoji",
                name="Kiyotaka Ayanokoji",
                aliases=["Ayanokoji"],
            ),
            Character(
                id="suzune_horikita",
                name="Suzune Horikita",
                aliases=["Horikita"],
            ),
        ]
    )
    stripped = strip_speech_attribution_tags(response)
    assert "perguntou" not in stripped.dialogues[0].text.casefold()
    assert "perguntei" not in stripped.dialogues[1].text.casefold()
    check_speaker_diarization(
        stripped,
        unit_text="Horikita perguntou. Ayanokoji respondeu.",
        story_state=story,
    )


def test_attribution_mismatch_rejected() -> None:
    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="kiyotaka_ayanokoji",
                emotion=Emotion.NEUTRAL,
                text="‘Acordado?’ perguntou Horikita.",
            ),
        ]
    )
    story = StoryState(
        characters=[
            Character(id="kiyotaka_ayanokoji", name="Ayanokoji", aliases=[]),
            Character(id="suzune_horikita", name="Horikita", aliases=["Suzune"]),
        ]
    )
    with pytest.raises(SpeakerQAError, match="speaker QA attribution"):
        check_speaker_diarization(
            response,
            unit_text="Horikita falou.",
            story_state=story,
        )


def test_unknown_attribution_name_does_not_false_positive() -> None:
    from audiobook_ai.llm.speaker_qa import strip_speech_attribution_tags

    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="narrator",
                emotion=Emotion.NEUTRAL,
                text="Alguém gritou ao longe.",
            ),
            Dialogue(
                speaker_id="kiyotaka_ayanokoji",
                emotion=Emotion.NEUTRAL,
                text="‘Oi.’ disse AlguémDesconhecido.",
            ),
        ]
    )
    story = StoryState(
        characters=[Character(id="kiyotaka_ayanokoji", name="Ayanokoji", aliases=[])]
    )
    stripped = strip_speech_attribution_tags(response)
    check_speaker_diarization(
        stripped,
        unit_text="disse AlguémDesconhecido",
        story_state=story,
    )


def test_few_quoted_turns_pass_even_if_one_speaker() -> None:
    response = LLMChapterResponse(
        dialogues=[
            Dialogue(speaker_id="a", emotion=Emotion.NEUTRAL, text=f"‘Linha {i}.’")
            for i in range(3)
        ]
    )
    story = StoryState(
        characters=[
            Character(id="a", name="Alice", aliases=[]),
            Character(id="b", name="Bob", aliases=[]),
            Character(id="c", name="Carol", aliases=[]),
        ]
    )
    check_speaker_diarization(
        response,
        unit_text="Alice falou. Bob e Carol estavam perto. disse Bob. respondeu Carol.",
        story_state=story,
    )


def test_ptbr_calque_with_correct_speakers_passes() -> None:
    """Adaptation quality is out of scope for speaker QA."""
    from audiobook_ai.llm.speaker_qa import strip_speech_attribution_tags

    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="narrator",
                emotion=Emotion.NEUTRAL,
                text="Meu cérebro, like a computer, executou the cálculos instantaneamente.",
            ),
            Dialogue(
                speaker_id="suzune_horikita",
                emotion=Emotion.NEUTRAL,
                text="‘Wake up agora or punishment.’ perguntou Horikita.",
            ),
            Dialogue(
                speaker_id="kiyotaka_ayanokoji",
                emotion=Emotion.NEUTRAL,
                text="‘What do you mean com punição?’",
            ),
        ]
    )
    story = StoryState(
        characters=[
            Character(id="kiyotaka_ayanokoji", name="Ayanokoji", aliases=[]),
            Character(id="suzune_horikita", name="Horikita", aliases=[]),
        ]
    )
    stripped = strip_speech_attribution_tags(response)
    check_speaker_diarization(
        stripped,
        unit_text="Horikita and Ayanokoji talked. Bad Portuguese is fine for this gate.",
        story_state=story,
    )


def test_ch004_speech_tag_fixture_rejects_without_strip() -> None:
    data = json.loads((_FIXTURES / "ch004_speech_tags.json").read_text(encoding="utf-8"))
    response = LLMChapterResponse.model_validate(data["tagged_response"])
    story = _story_from_fixture(data)
    with pytest.raises(SpeakerQAError, match="speaker QA speech-tag"):
        check_speaker_diarization(
            response,
            unit_text=data["unit_text"],
            story_state=story,
        )


def test_ch004_speech_tag_strip_then_passes() -> None:
    from audiobook_ai.llm.speaker_qa import strip_speech_attribution_tags

    data = json.loads((_FIXTURES / "ch004_speech_tags.json").read_text(encoding="utf-8"))
    response = LLMChapterResponse.model_validate(data["tagged_response"])
    story = _story_from_fixture(data)
    stripped = strip_speech_attribution_tags(response)
    assert stripped.dialogues[0].text == '"Como eu sabia, você já estava acordado."'
    assert stripped.dialogues[1].text == '"Prova?"'
    check_speaker_diarization(
        stripped,
        unit_text=data["unit_text"],
        story_state=story,
    )


def test_narrator_disse_que_not_stripped_or_rejected() -> None:
    from audiobook_ai.llm.speaker_qa import strip_speech_attribution_tags

    data = json.loads((_FIXTURES / "ch004_speech_tags.json").read_text(encoding="utf-8"))
    response = LLMChapterResponse.model_validate(data["narrator_disse_que"])
    story = _story_from_fixture(data)
    original = response.dialogues[0].text
    stripped = strip_speech_attribution_tags(response)
    assert stripped.dialogues[0].text == original
    check_speaker_diarization(
        stripped,
        unit_text=original,
        story_state=story,
    )


def test_empty_text_after_strip_raises() -> None:
    from audiobook_ai.llm.speaker_qa import strip_speech_attribution_tags

    response = LLMChapterResponse(
        dialogues=[
            Dialogue(
                speaker_id="suzune_horikita",
                emotion=Emotion.NEUTRAL,
                text=" disse ela.",
            ),
        ]
    )
    with pytest.raises(SpeakerQAError, match="empty text after strip"):
        strip_speech_attribution_tags(response)
