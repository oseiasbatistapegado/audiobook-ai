"""Unit tests for packaged default voice resolution and pt-BR policy."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.tts.fish_speech import FishSpeechBackend
from audiobook_ai.tts.voices import (
    DEFAULT_VOICE_ID,
    packaged_voice_dir,
    project_assets_voices_root,
    resolve_voice_dir,
    voice_language,
)
from audiobook_ai.weights.fish import FISH_SPEECH_ID, FISH_SPEECH_REQUIRED_FILES
from audiobook_ai.weights.manager import ModelManager


def _touch_required(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in FISH_SPEECH_REQUIRED_FILES:
        (dest / name).write_bytes(b"ok")


def _write_voice(
    directory: Path,
    *,
    language: str | None = "pt-BR",
    text: str = "olá\n",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "reference.wav").write_bytes(b"RIFF....WAVEfmt ")
    (directory / "reference.lab").write_text(text, encoding="utf-8")
    if language is not None:
        (directory / "metadata.json").write_text(
            json.dumps({"language": language}, ensure_ascii=False),
            encoding="utf-8",
        )
    return directory


class _FakeEngine:
    def __init__(self) -> None:
        self.last_req: object | None = None

    def inference(self, req: object) -> list[SimpleNamespace]:
        self.last_req = req
        return [
            SimpleNamespace(code="final", audio=(44100, b"RIFF....WAVEfmt ")),
        ]


def test_packaged_narrator_assets_exist() -> None:
    root = project_assets_voices_root()
    narrator = packaged_voice_dir(DEFAULT_VOICE_ID)
    assert narrator is not None
    assert narrator == root / DEFAULT_VOICE_ID
    assert (narrator / "reference.wav").is_file()
    assert (narrator / "reference.lab").is_file()
    assert voice_language(narrator) == "pt-BR"
    lab = (narrator / "reference.lab").read_text(encoding="utf-8").casefold()
    assert "português" in lab or "brasil" in lab or "olá" in lab


def test_packaged_character_bases_exist() -> None:
    root = project_assets_voices_root()
    bases = [
        path
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("base_")
    ]
    assert len(bases) >= 5
    for base in bases:
        assert voice_language(base) == "pt-BR"


def test_resolve_uses_packaged_assets_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    voice_id, voice_dir = resolve_voice_dir("narrator", cache_root=tmp_path / "cache")
    assert voice_id == "narrator"
    assert voice_dir == packaged_voice_dir("narrator")


def test_resolve_prefers_user_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _write_voice(tmp_path / "references" / "narrator", language=None)
    monkeypatch.chdir(tmp_path)
    voice_id, voice_dir = resolve_voice_dir("narrator", cache_root=tmp_path / "cache")
    assert voice_id == "narrator"
    assert voice_dir == user


def test_resolve_prefers_registry_over_packaged(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    registry = _write_voice(cache / "voices" / "carlos")
    voice_id, voice_dir = resolve_voice_dir("carlos", cache_root=cache)
    assert voice_id == "carlos"
    assert voice_dir == registry


def test_resolve_prefers_injected_references_dir(tmp_path: Path) -> None:
    injected = _write_voice(tmp_path / "references" / "narrator", language=None)
    voice_id, voice_dir = resolve_voice_dir(
        "narrator",
        references_dir=tmp_path / "references",
        cache_root=tmp_path / "cache",
    )
    assert voice_id == "narrator"
    assert voice_dir == injected


def test_unknown_voice_falls_back_to_narrator_pt_br(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.WARNING):
        voice_id, voice_dir = resolve_voice_dir(
            "missing-voice-xyz", cache_root=tmp_path / "cache"
        )
    assert voice_id == "narrator"
    assert voice_dir == packaged_voice_dir("narrator")
    assert any("falling back" in record.message for record in caplog.records)


def test_rejects_non_pt_br_packaged_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_assets = tmp_path / "assets" / "voices"
    _write_voice(fake_assets / "en-only", language="en-US")
    monkeypatch.setattr(
        "audiobook_ai.tts.voices.project_assets_voices_root",
        lambda: fake_assets,
    )
    with pytest.raises(FileNotFoundError, match="pt-BR"):
        resolve_voice_dir("en-only", cache_root=tmp_path / "cache")


def test_synthesize_uses_resolved_packaged_voice(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / FISH_SPEECH_ID)
    engine = _FakeEngine()
    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))
    backend = FishSpeechBackend(
        manager=manager,
        engine_factory=lambda *_: engine,
        require_gpu=False,
        device="cpu",
    )
    segment = backend.synthesize(
        TTSRequest(text="Olá", voice_id="narrator", emotion=Emotion.NEUTRAL)
    )
    assert segment.data
    assert getattr(engine.last_req, "reference_id", None) == "narrator"


def test_synthesize_unknown_voice_falls_back(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / FISH_SPEECH_ID)
    engine = _FakeEngine()
    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))
    backend = FishSpeechBackend(
        manager=manager,
        engine_factory=lambda *_: engine,
        require_gpu=False,
        device="cpu",
    )
    with caplog.at_level(logging.WARNING):
        segment = backend.synthesize(
            TTSRequest(text="Olá", voice_id="no-such-voice", emotion=Emotion.NEUTRAL)
        )
    assert segment.data
    assert getattr(engine.last_req, "reference_id", None) == "narrator"
    assert any("falling back" in record.message for record in caplog.records)
