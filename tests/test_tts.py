"""Qwen3-TTS in-process backend tests (engine/manager mocked)."""

from __future__ import annotations

from pathlib import Path

import pytest

from audiobook_ai.models.emotion import Emotion
from audiobook_ai.models.tts import TTSRequest
from audiobook_ai.tts.factory import get_tts_backend
from audiobook_ai.tts.qwen3_tts import Qwen3TTSBackend, Qwen3TTSError
from audiobook_ai.weights.manager import ModelManager
from audiobook_ai.weights.qwen3_tts import QWEN3_TTS_ID, QWEN3_TTS_REQUIRED_FILES


def _touch_required(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in QWEN3_TTS_REQUIRED_FILES:
        path = dest / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ok")


class _FakeEngine:
    def __init__(self) -> None:
        self.calls = 0
        self.prompt_calls = 0
        self.last_kwargs: dict | None = None

    def create_voice_clone_prompt(self, **kwargs: object) -> list[dict]:
        self.prompt_calls += 1
        return [{"ref": kwargs.get("ref_audio"), "text": kwargs.get("ref_text")}]

    def generate_voice_clone(self, **kwargs: object) -> tuple[list, int]:
        self.calls += 1
        self.last_kwargs = dict(kwargs)
        text = kwargs.get("text")
        n = len(text) if isinstance(text, list) else 1
        # int16-compatible list; backend converts without requiring float numpy.
        return [[0] * 2400 for _ in range(n)], 24000


def _voice_refs(tmp_path: Path) -> Path:
    """Minimal pt-BR voice reference tree for unit tests."""
    voice = tmp_path / "references" / "narrator"
    voice.mkdir(parents=True)
    (voice / "reference.wav").write_bytes(b"RIFF....WAVE")
    (voice / "reference.txt").write_text("olá mundo\n", encoding="utf-8")
    (voice / "metadata.json").write_text(
        '{"language": "pt-BR"}',
        encoding="utf-8",
    )
    return tmp_path / "references"


def test_factory_returns_qwen3_tts() -> None:
    backend = get_tts_backend("qwen3-tts")
    assert isinstance(backend, Qwen3TTSBackend)
    assert isinstance(get_tts_backend("qwen3tts"), Qwen3TTSBackend)


def test_factory_rejects_fish_and_cosyvoice() -> None:
    for name in ("fish-speech", "s1-mini", "cosyvoice", "cosyvoice3"):
        with pytest.raises(ValueError, match="qwen3-tts|no longer supported|Only"):
            get_tts_backend(name)


def test_synthesize_reuses_loaded_engine_within_worker(tmp_path: Path) -> None:
    """Within one TTS worker invocation the engine is reused across chunks."""
    cache = tmp_path / "cache"
    _touch_required(cache / QWEN3_TTS_ID)
    refs = _voice_refs(tmp_path)
    engine = _FakeEngine()

    def factory(model_path: Path, device: str) -> _FakeEngine:
        assert model_path == cache / QWEN3_TTS_ID
        assert device == "cpu"
        return engine

    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))
    backend = Qwen3TTSBackend(
        manager=manager,
        engine_factory=factory,
        require_gpu=False,
        device="cpu",
        references_dir=refs,
    )
    req = TTSRequest(text="Hello", voice_id="narrator", emotion=Emotion.ANGRY)
    first = backend.synthesize(req)
    second = backend.synthesize(req)
    assert first.data and second.data
    assert engine.calls == 2
    assert engine.prompt_calls == 1  # VoiceClonePrompt cached per voice_id
    assert backend._loaded is True
    assert engine.last_kwargs is not None
    assert "instruct" not in engine.last_kwargs
    assert "emotion" not in engine.last_kwargs
    assert engine.last_kwargs.get("language") == "Portuguese"
    assert engine.last_kwargs.get("text") == "Hello"
    assert "voice_clone_prompt" in engine.last_kwargs


def test_synthesize_batch_same_voice(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / QWEN3_TTS_ID)
    refs = _voice_refs(tmp_path)
    engine = _FakeEngine()

    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))
    backend = Qwen3TTSBackend(
        manager=manager,
        engine_factory=lambda *_: engine,
        require_gpu=False,
        device="cpu",
        references_dir=refs,
    )
    reqs = [
        TTSRequest(text="One", voice_id="narrator", emotion=Emotion.NEUTRAL, segment_index=0),
        TTSRequest(text="Two", voice_id="narrator", emotion=Emotion.NEUTRAL, segment_index=1),
    ]
    segs = backend.synthesize_batch(reqs)
    assert len(segs) == 2
    assert engine.calls == 1
    assert engine.prompt_calls == 1
    assert engine.last_kwargs is not None
    assert engine.last_kwargs.get("text") == ["One", "Two"]


def test_missing_import_is_clear(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / QWEN3_TTS_ID)
    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: Path("unused"))

    def boom(model_path: Path, device: str) -> _FakeEngine:
        raise ImportError("No module named 'qwen_tts'")

    backend = Qwen3TTSBackend(
        manager=manager,
        engine_factory=boom,
        require_gpu=False,
        device="cpu",
    )
    with pytest.raises(Qwen3TTSError, match="not installed|tts-qwen|qwen"):
        backend.synthesize(TTSRequest(text="Hello", voice_id="narrator"))


def test_gpu_required_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _touch_required(cache / QWEN3_TTS_ID)
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

    monkeypatch.setitem(__import__("sys").modules, "torch", _Torch())

    backend = Qwen3TTSBackend(
        manager=manager,
        engine_factory=lambda *_: _FakeEngine(),
        require_gpu=True,
    )
    with pytest.raises(Qwen3TTSError, match="GPU"):
        backend.synthesize(TTSRequest(text="Hello", voice_id="narrator"))


def test_ensure_weights_without_engine(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    calls: list[str] = []

    def fake_download(**kwargs: object) -> Path:
        calls.append("download")
        local_dir = Path(str(kwargs["local_dir"]))
        _touch_required(local_dir)
        return local_dir

    manager = ModelManager(cache_dir=cache, hub_download=fake_download)
    backend = Qwen3TTSBackend(manager=manager, require_gpu=False, device="cpu")
    handle = backend.ensure_weights()
    assert handle.logical_id == QWEN3_TTS_ID
    assert calls == ["download"]
    assert backend._engine is None
