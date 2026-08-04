"""CLI option surface for VRAM / chunk overrides."""

from __future__ import annotations

from typer.testing import CliRunner

from audiobook_ai.cli import app

runner = CliRunner()


def test_generate_help_exposes_vram_and_chunk_flags() -> None:
    result = runner.invoke(app, ["generate", "--help"])
    assert result.exit_code == 0
    assert "--hard-floor-mib" in result.output
    assert "--before-chunk-target-mib" in result.output
    assert "--tts-before-load-target-mib" in result.output
    assert "--parler-before-load-target" in result.output
    assert "--tts-max-chunk-chars" in result.output
    assert "--tts-chunks-per-worker" in result.output
    assert "--fish-model" not in result.output
    assert "--fish-before-load" not in result.output
    assert "guardian-driven" in result.output.lower() or "escape hatch" in result.output.lower()
    assert "chunking_fingerprint" in result.output or "invalidates" in result.output.lower()


def test_generate_help_mentions_qwen3_not_fish() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Qwen3-TTS" in result.output or "qwen" in result.output.lower()
    assert "8080" not in result.output
