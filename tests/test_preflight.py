"""Preflight dependency checks (ffmpeg, Ollama, TTS imports)."""

from __future__ import annotations

import pytest

from audiobook_ai.preflight import (
    PreflightError,
    check_ffmpeg,
    check_ollama,
    check_tts_python_imports,
    run_preflight,
)


def test_ffmpeg_missing() -> None:
    with pytest.raises(PreflightError, match="ffmpeg|direnv"):
        check_ffmpeg(which=lambda _name: None)


def test_ffmpeg_present() -> None:
    check_ffmpeg(which=lambda name: f"/usr/bin/{name}")


def test_ollama_unreachable() -> None:
    def boom(_host: str) -> list[str]:
        raise PreflightError(
            "Ollama host is not reachable at 'http://localhost:11434': connection refused. "
            "Start Ollama (e.g. `ollama serve`) and confirm --ollama-host / OLLAMA_HOST."
        )

    with pytest.raises(PreflightError, match="not reachable|ollama"):
        check_ollama(
            ollama_host="http://localhost:11434",
            model="qwen3.6:27b",
            list_models=boom,
        )


def test_ollama_model_missing() -> None:
    with pytest.raises(PreflightError, match="ollama pull"):
        check_ollama(
            ollama_host="http://localhost:11434",
            model="missing-model:7b",
            list_models=lambda _host: ["other:latest"],
        )


def test_ollama_model_present() -> None:
    check_ollama(
        ollama_host="http://localhost:11434",
        model="qwen3.6:27b",
        list_models=lambda _host: ["qwen3.6:27b"],
    )


def test_fish_speech_import_missing() -> None:
    def boom(_names: object) -> None:
        raise ImportError("No module named 'fish_speech'")

    with pytest.raises(PreflightError, match="tts-fish|fish-speech"):
        check_tts_python_imports(import_modules=boom)


def test_run_preflight_stops_before_later_checks() -> None:
    calls: list[str] = []

    def which(name: str) -> str | None:
        calls.append(f"which:{name}")
        return None

    def list_models(_host: str) -> list[str]:
        calls.append("ollama")
        return ["qwen3.6:27b"]

    def import_modules(_names: object) -> None:
        calls.append("imports")

    with pytest.raises(PreflightError, match="ffmpeg"):
        run_preflight(
            ollama_host="http://localhost:11434",
            model="qwen3.6:27b",
            which=which,
            list_ollama_models=list_models,
            import_modules=import_modules,
        )
    assert calls == ["which:ffmpeg"]
    assert "ollama" not in calls
    assert "imports" not in calls


def test_run_preflight_ok() -> None:
    run_preflight(
        ollama_host="http://localhost:11434",
        model="qwen3.6:27b",
        which=lambda name: f"/bin/{name}",
        list_ollama_models=lambda _host: ["qwen3.6:27b"],
        import_modules=lambda _names: None,
    )
