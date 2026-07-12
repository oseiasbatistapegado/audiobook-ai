"""Fish Speech in-process backend tests (engine/manager mocked)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.tts.factory import get_tts_backend
from audiobook_ai.tts.fish_speech import FishSpeechBackend, FishSpeechError
from audiobook_ai.weights.fish import FISH_SPEECH_ID, FISH_SPEECH_REQUIRED_FILES
from audiobook_ai.weights.manager import ModelManager


def _touch_required(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in FISH_SPEECH_REQUIRED_FILES:
        (dest / name).write_bytes(b"ok")


class _FakeEngine:
    def __init__(self) -> None:
        self.calls = 0

    def inference(self, req: object) -> list[SimpleNamespace]:
        self.calls += 1
        return [
            SimpleNamespace(code="final", audio=(44100, b"RIFF....WAVEfmt ")),
        ]


def _voice_refs(tmp_path: Path) -> Path:
    """Minimal pt-BR voice reference tree for unit tests (no packaged assets)."""
    voice = tmp_path / "references" / "narrator"
    voice.mkdir(parents=True)
    (voice / "reference.wav").write_bytes(b"RIFF....WAVE")
    (voice / "reference.lab").write_text("olá\n", encoding="utf-8")
    return tmp_path / "references"


def test_factory_returns_fish_speech() -> None:
    backend = get_tts_backend("fish-speech")
    assert isinstance(backend, FishSpeechBackend)


def test_synthesize_reuses_loaded_engine_within_worker(tmp_path: Path) -> None:
    """Within one Fish worker invocation the engine is reused across chunks."""
    cache = tmp_path / "cache"
    _touch_required(cache / FISH_SPEECH_ID)
    refs = _voice_refs(tmp_path)
    engine = _FakeEngine()

    def factory(model_path: Path, device: str) -> _FakeEngine:
        assert model_path == cache / FISH_SPEECH_ID
        assert device == "cpu"
        return engine

    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))
    backend = FishSpeechBackend(
        manager=manager,
        engine_factory=factory,
        require_gpu=False,
        device="cpu",
        references_dir=refs,
    )
    req = TTSRequest(text="Hello", voice_id="narrator", emotion=Emotion.NEUTRAL)
    first = backend.synthesize(req)
    second = backend.synthesize(req)
    assert first.data and second.data
    assert engine.calls == 2
    # factory invoked once (load once) — restart is orchestrator/worker exit
    assert backend._loaded is True


def test_missing_import_is_clear(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / FISH_SPEECH_ID)
    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))

    def boom(model_path: Path, device: str) -> _FakeEngine:
        raise ImportError("No module named 'fish_speech'")

    backend = FishSpeechBackend(
        manager=manager,
        engine_factory=boom,
        require_gpu=False,
        device="cpu",
    )
    with pytest.raises(FishSpeechError, match="not installed|tts-fish|fish-speech"):
        backend.synthesize(TTSRequest(text="Hello", voice_id="narrator"))


def test_invalid_weights_error(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / FISH_SPEECH_ID)
    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))

    def boom(model_path: Path, device: str) -> _FakeEngine:
        raise FishSpeechError(f"Invalid Fish Speech weights: missing codec.pth under {model_path}")

    backend = FishSpeechBackend(
        manager=manager,
        engine_factory=boom,
        require_gpu=False,
        device="cpu",
    )
    with pytest.raises(FishSpeechError, match="Invalid Fish Speech weights"):
        backend.synthesize(TTSRequest(text="Hello", voice_id="narrator"))


def test_gpu_required_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / FISH_SPEECH_ID)
    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))

    class _Torch:
        class cuda:
            @staticmethod
            def is_available() -> bool:
                return False

        class backends:
            class mps:
                @staticmethod
                def is_available() -> bool:
                    return False

    import audiobook_ai.tts.fish_speech as mod

    monkeypatch.setitem(__import__("sys").modules, "torch", _Torch())
    # Force resolve path without injected device
    backend = FishSpeechBackend(
        manager=manager,
        engine_factory=lambda *_: _FakeEngine(),
        require_gpu=True,
        device=None,
    )
    # Patch _resolve_device to use our fake torch via import inside function —
    # inject by patching the helper.
    monkeypatch.setattr(
        mod,
        "_resolve_device",
        lambda require_gpu=True: (_ for _ in ()).throw(
            FishSpeechError("No usable GPU detected")
        ),
    )
    with pytest.raises(FishSpeechError, match="GPU"):
        backend.ensure_ready()


def test_ensure_weights_does_not_load_engine(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / FISH_SPEECH_ID)
    loads = 0

    def factory(model_path: Path, device: str) -> _FakeEngine:
        nonlocal loads
        loads += 1
        return _FakeEngine()

    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))
    backend = FishSpeechBackend(
        manager=manager,
        engine_factory=factory,
        require_gpu=False,
        device="cpu",
    )
    handle = backend.ensure_weights()
    assert handle.path == cache / FISH_SPEECH_ID
    assert loads == 0
    assert backend._loaded is False


def test_release_idempotent_and_reload(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / FISH_SPEECH_ID)
    refs = _voice_refs(tmp_path)
    engines: list[_FakeEngine] = []

    def factory(model_path: Path, device: str) -> _FakeEngine:
        engine = _FakeEngine()
        engines.append(engine)
        return engine

    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))
    backend = FishSpeechBackend(
        manager=manager,
        engine_factory=factory,
        require_gpu=False,
        device="cpu",
        references_dir=refs,
    )
    req = TTSRequest(text="Hello", voice_id="narrator", emotion=Emotion.NEUTRAL)
    backend.synthesize(req)
    assert len(engines) == 1
    assert backend._loaded is True

    backend.release()
    assert backend._loaded is False
    assert backend._engine is None
    backend.release()  # idempotent

    again = backend.synthesize(req)
    assert again.data
    assert len(engines) == 2
    assert backend._loaded is True
