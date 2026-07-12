"""Unit tests for ModelManager (hub mocked, tmp_path cache)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from audiobook_ai.weights.cache import resolve_cache_root
from audiobook_ai.weights.fish import (
    FISH_S1_MINI_ID,
    FISH_S1_MINI_REQUIRED_FILES,
    FISH_S1_MINI_REVISION,
    FISH_S2_PRO_ID,
    FISH_S2_PRO_REQUIRED_FILES,
    FISH_S2_PRO_REVISION,
    FISH_SPEECH_ID,
    FISH_SPEECH_REQUIRED_FILES,
    FISH_SPEECH_REVISION,
    FishSpeechModel,
    list_fish_model_aliases,
    resolve_fish_model,
)
from audiobook_ai.weights.manager import ModelManager


def _touch_required(dest: Path, required: tuple[str, ...] | None = None) -> None:
    files = required or FISH_SPEECH_REQUIRED_FILES
    dest.mkdir(parents=True, exist_ok=True)
    for name in files:
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


def test_fish_model_rejects_main_revision() -> None:
    with pytest.raises(ValueError, match="main"):
        FishSpeechModel(
            alias="bad",
            logical_id="bad",
            repository="fishaudio/openaudio-s1-mini",
            revision="main",
            required_files=FISH_S1_MINI_REQUIRED_FILES,
            tts_max_chunk_chars=200,
            before_load_target_mib=8192,
        )


def test_resolve_fish_model_aliases() -> None:
    s1 = resolve_fish_model("s1-mini")
    s2 = resolve_fish_model("s2-pro")
    assert s1.logical_id == FISH_S1_MINI_ID
    assert s2.logical_id == FISH_S2_PRO_ID
    assert s1.repository == "fishaudio/openaudio-s1-mini"
    assert s2.repository == "fishaudio/s2-pro"
    assert s1.tts_max_chunk_chars == 200
    assert s2.tts_max_chunk_chars == 80
    assert s1.before_load_target_mib == 8192
    assert s2.before_load_target_mib == 22528
    assert set(list_fish_model_aliases()) == {"s1-mini", "s2-pro"}
    with pytest.raises(ValueError, match="Valid --fish-model"):
        resolve_fish_model("nope")


def test_ensure_skips_download_when_intact(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_download(**kwargs: object) -> Path:
        calls.append("download")
        local_dir = Path(str(kwargs["local_dir"]))
        _touch_required(local_dir)
        return local_dir

    cache = tmp_path / "cache"
    model_path = cache / FISH_SPEECH_ID
    _touch_required(model_path)

    manager = ModelManager(cache_dir=cache, hub_download=fake_download)
    first = manager.ensure_model(FISH_SPEECH_ID)
    second = manager.ensure_model(FISH_SPEECH_ID)
    assert first.path == second.path == model_path
    assert calls == []
    assert manager.get_model(FISH_SPEECH_ID).revision == FISH_SPEECH_REVISION
    assert manager.get_model(FISH_SPEECH_ID).revision != "main"


def test_ensure_downloads_when_missing(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_download(**kwargs: object) -> Path:
        calls.append(kwargs)
        local_dir = Path(str(kwargs["local_dir"]))
        _touch_required(local_dir)
        return local_dir

    manager = ModelManager(cache_dir=tmp_path / "cache", hub_download=fake_download)
    handle = manager.ensure_model(FISH_SPEECH_ID)
    assert handle.path.is_dir()
    assert len(calls) == 1
    assert calls[0]["revision"] == FISH_S1_MINI_REVISION
    assert calls[0]["revision"] != "main"
    assert calls[0]["repository"] == "fishaudio/openaudio-s1-mini"


def test_ensure_s2_pro_uses_separate_cache(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_download(**kwargs: object) -> Path:
        calls.append(kwargs)
        local_dir = Path(str(kwargs["local_dir"]))
        patterns = tuple(kwargs.get("allow_patterns") or ())  # type: ignore[arg-type]
        required = tuple(patterns) if patterns else FISH_S1_MINI_REQUIRED_FILES
        _touch_required(local_dir, required)
        return local_dir

    cache = tmp_path / "cache"
    manager = ModelManager(cache_dir=cache, hub_download=fake_download)
    s1 = manager.ensure_fish_alias("s1-mini")
    s2 = manager.ensure_fish_alias("s2-pro")
    assert s1.path == cache / FISH_S1_MINI_ID
    assert s2.path == cache / FISH_S2_PRO_ID
    assert s1.path != s2.path
    assert calls[0]["repository"] == "fishaudio/openaudio-s1-mini"
    assert calls[1]["repository"] == "fishaudio/s2-pro"
    assert calls[1]["revision"] == FISH_S2_PRO_REVISION


def test_migrate_legacy_fish_speech_cache_to_s2_pro(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_download(**kwargs: object) -> Path:
        calls.append("download")
        return Path(str(kwargs["local_dir"]))

    cache = tmp_path / "cache"
    legacy = cache / "fish-speech"
    _touch_required(legacy, FISH_S2_PRO_REQUIRED_FILES)
    manager = ModelManager(cache_dir=cache, hub_download=fake_download)
    handle = manager.ensure_fish_alias("s2-pro")
    assert handle.path == cache / FISH_S2_PRO_ID
    assert calls == []
    for name in FISH_S2_PRO_REQUIRED_FILES:
        assert (handle.path / name).is_file()

    def fake_download(**kwargs: object) -> Path:
        raise RuntimeError(
            "401 Client Error: Cannot access gated repo for url "
            "https://huggingface.co/fishaudio/openaudio-s1-mini"
        )

    manager = ModelManager(cache_dir=tmp_path / "cache", hub_download=fake_download)
    with pytest.raises(RuntimeError, match="hf auth login"):
        manager.ensure_fish_alias("s1-mini")


def test_ensure_repairs_incomplete_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    model_path = cache / FISH_SPEECH_ID
    model_path.mkdir(parents=True)
    (model_path / "config.json").write_bytes(b"partial")

    def fake_download(**kwargs: object) -> Path:
        local_dir = Path(str(kwargs["local_dir"]))
        _touch_required(local_dir)
        return local_dir

    manager = ModelManager(cache_dir=cache, hub_download=fake_download)
    handle = manager.ensure_model(FISH_SPEECH_ID)
    for name in FISH_SPEECH_REQUIRED_FILES:
        assert (handle.path / name).is_file()


def test_get_model_requires_ensure(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    model_path = cache / FISH_SPEECH_ID
    model_path.mkdir(parents=True)
    manager = ModelManager(cache_dir=cache, hub_download=lambda **_: model_path)
    with pytest.raises(FileNotFoundError, match="not ready"):
        manager.get_model(FISH_SPEECH_ID)
    _touch_required(model_path)
    handle = manager.ensure_model(FISH_SPEECH_ID)
    assert handle.path == model_path


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
        results.append(manager.ensure_model(FISH_SPEECH_ID).path)

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
