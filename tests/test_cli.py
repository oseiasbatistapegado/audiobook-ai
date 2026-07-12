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
    assert "--fish-before-load-target-mib" in result.output
    assert "--parler-before-load-target" in result.output
    assert "--tts-max-chunk-chars" in result.output
    assert "--fish-chunks-per-worker" in result.output
    assert "--fish-model" in result.output
    assert "s1-mini" in result.output
    assert "guardian-driven" in result.output.lower() or "escape hatch" in result.output.lower()
    assert "--fish-speech-url" not in result.output


def test_generate_rejects_unknown_fish_model(tmp_path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    result = runner.invoke(
        app,
        ["generate", str(pdf), "--fish-model", "not-a-model", "--work-dir", str(tmp_path / "out")],
    )
    assert result.exit_code == 1
    assert "fish-model" in result.output.lower() or "Valid" in result.output


def test_generate_help_mentions_workers_not_http_server() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Root help should not advertise an HTTP Fish URL workflow.
    assert "8080" not in result.output
