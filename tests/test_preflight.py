"""Preflight dependency checks (ffmpeg, llama-server, TTS imports)."""

from __future__ import annotations

import unittest.mock

import pytest

from audiobook_ai.preflight import (
    PreflightError,
    check_ffmpeg,
    check_llama_server,
    run_preflight,
)


def test_ffmpeg_missing() -> None:
    with pytest.raises(PreflightError, match="ffmpeg|direnv"):
        check_ffmpeg(which=lambda _name: None)


def test_ffmpeg_present() -> None:
    check_ffmpeg(which=lambda name: f"/usr/bin/{name}")


def test_llama_server_unreachable() -> None:
    with pytest.raises(PreflightError, match="not reachable|llama-server"):
        with unittest.mock.patch("httpx.Client") as mock_client:
            mock_client.side_effect = Exception("connection refused")
            check_llama_server(
                llama_host="http://localhost:19999",
                model="qwen3.6:27b",
                check_llama_bin=False,
            )


def test_run_preflight_stops_before_later_checks() -> None:
    calls: list[str] = []

    def which(name: str) -> str | None:
        calls.append(f"which:{name}")
        return None

    def import_modules(_names: object) -> None:
        calls.append("imports")

    with pytest.raises(PreflightError, match="ffmpeg"):
        run_preflight(
            llama_host="http://127.0.0.1:8080",
            model="qwen3.6:27b",
            which=which,
            import_modules=import_modules,
        )
    assert calls == ["which:ffmpeg"]


def test_run_preflight_ok() -> None:
    run_preflight(
        llama_host="http://127.0.0.1:8080",
        model="qwen3.6:27b",
        which=lambda name: f"/bin/{name}",
        import_modules=lambda _names: None,
    )
