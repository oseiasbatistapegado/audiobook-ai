"""Unit tests for ModelManager (hub mocked, tmp_path cache)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from audiobook_ai.weights.cache import resolve_cache_root
from audiobook_ai.weights.definition import PinnedModel
from audiobook_ai.weights.manager import ModelManager
from audiobook_ai.weights.qwen3_tts import (
    QWEN3_TTS_ID,
    QWEN3_TTS_REQUIRED_FILES,
    QWEN3_TTS_REVISION,
    QWEN3_TTS_REPOSITORY,
)


def _touch_required(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in QWEN3_TTS_REQUIRED_FILES:
        path = dest / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ok")


def test_resolve_cache_root_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cli = tmp_path / "cli-cache"
    env = tmp_path / "env-cache"
    monkeypatch.setenv("AUDIOBOOK_AI_CACHE_DIR", str(env))
    assert resolve_cache_root(cli) == cli.resolve()
    assert resolve_cache_root(None) == env.resolve()
    monkeypatch.delenv("AUDIOBOOK_AI_CACHE_DIR")
    assert resolve_cache_root(None) == (Path.home() / ".cache/audiobook-ai").resolve()


def test_pinned_model_rejects_main_revision() -> None:
    with pytest.raises(ValueError, match="main"):
        PinnedModel(
            logical_id="bad",
            repository=QWEN3_TTS_REPOSITORY,
            revision="main",
            required_files=QWEN3_TTS_REQUIRED_FILES,
        )


def test_ensure_skips_download_when_intact(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_download(**kwargs: object) -> Path:
        calls.append("download")
        local_dir = Path(str(kwargs["local_dir"]))
        _touch_required(local_dir)
        return local_dir

    cache = tmp_path / "cache"
    model_path = cache / QWEN3_TTS_ID
    _touch_required(model_path)

    manager = ModelManager(cache_dir=cache, hub_download=fake_download)
    first = manager.ensure_model(QWEN3_TTS_ID)
    second = manager.ensure_model()
    assert first.path == second.path == model_path
    assert calls == []
    assert manager.get_model(QWEN3_TTS_ID).revision == QWEN3_TTS_REVISION
    assert manager.get_model(QWEN3_TTS_ID).revision != "main"


def test_ensure_downloads_when_missing(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_download(**kwargs: object) -> Path:
        calls.append(kwargs)
        local_dir = Path(str(kwargs["local_dir"]))
        _touch_required(local_dir)
        return local_dir

    manager = ModelManager(cache_dir=tmp_path / "cache", hub_download=fake_download)
    handle = manager.ensure_model(QWEN3_TTS_ID)
    assert handle.path.is_dir()
    assert len(calls) == 1
    assert calls[0]["revision"] == QWEN3_TTS_REVISION
    assert calls[0]["revision"] != "main"
    assert calls[0]["repository"] == QWEN3_TTS_REPOSITORY


def test_ensure_repairs_incomplete_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    model_path = cache / QWEN3_TTS_ID
    model_path.mkdir(parents=True)
    (model_path / "config.json").write_bytes(b"partial")

    def fake_download(**kwargs: object) -> Path:
        local_dir = Path(str(kwargs["local_dir"]))
        _touch_required(local_dir)
        return local_dir

    manager = ModelManager(cache_dir=cache, hub_download=fake_download)
    handle = manager.ensure_model(QWEN3_TTS_ID)
    for name in QWEN3_TTS_REQUIRED_FILES:
        assert (handle.path / name).is_file()


def test_get_model_requires_ensure(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    model_path = cache / QWEN3_TTS_ID
    model_path.mkdir(parents=True)
    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: model_path)
    with pytest.raises(FileNotFoundError, match="not ready"):
        manager.get_model(QWEN3_TTS_ID)
    _touch_required(model_path)
    handle = manager.ensure_model(QWEN3_TTS_ID)
    assert handle.path == model_path


def test_hub_auth_error_is_actionable(tmp_path: Path) -> None:
    def fake_download_auth(**kwargs: object) -> Path:
        raise RuntimeError("401 Client Error: unauthorized")

    manager = ModelManager(cache_dir=tmp_path / "cache", hub_download=fake_download_auth)
    with pytest.raises(RuntimeError, match="hf auth login"):
        manager.ensure_model(QWEN3_TTS_ID)


def test_concurrent_ensure_single_download(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    lock = threading.Lock()

    def fake_download(**kwargs: object) -> Path:
        with lock:
            calls.append("download")
        started.set()
        assert release.wait(timeout=5)
        local_dir = Path(str(kwargs["local_dir"]))
        _touch_required(local_dir)
        time.sleep(0.05)
        return local_dir

    manager = ModelManager(cache_dir=tmp_path / "cache", hub_download=fake_download)
    results: list[Path] = []

    def worker() -> None:
        results.append(manager.ensure_model(QWEN3_TTS_ID).path)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    assert started.wait(timeout=5)
    release.set()
    for t in threads:
        t.join(timeout=10)
    assert len(calls) == 1
    assert len(results) == 2
    assert results[0] == results[1]
