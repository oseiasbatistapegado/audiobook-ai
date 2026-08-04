"""Tests for isolated worker Python resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from audiobook_ai.gpu.runtimes import (
    ENV_VOICE_DESIGN_PYTHON,
    resolve_tts_python,
    resolve_voice_design_python,
    worker_env,
)


def test_worker_env_scrubs_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/nix/store/fake:/other")
    monkeypatch.setenv("PYTHONHOME", "/nix/store/fake-home")
    monkeypatch.setenv("KEEP_ME", "1")
    env = worker_env()
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert env["KEEP_ME"] == "1"


def test_resolve_tts_python_defaults_to_sys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VOICE_DESIGN_PYTHON, raising=False)
    monkeypatch.delenv("AUDIOBOOK_AI_TTS_PYTHON", raising=False)
    assert Path(resolve_tts_python()).exists()


def test_resolve_voice_design_python_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "python"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv(ENV_VOICE_DESIGN_PYTHON, str(fake))
    assert resolve_voice_design_python() == str(fake.absolute())


def test_resolve_voice_design_prefers_venv_parler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_VOICE_DESIGN_PYTHON, raising=False)
    venv_py = tmp_path / ".venv-parler" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_py.chmod(0o755)
    assert resolve_voice_design_python(project_root=tmp_path) == str(venv_py.absolute())


def test_resolve_voice_design_keeps_venv_shim_not_base_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Symlinked venv python must not be resolved to the base interpreter."""
    monkeypatch.delenv(ENV_VOICE_DESIGN_PYTHON, raising=False)
    base = tmp_path / "base-python"
    base.write_text("#!/bin/sh\n", encoding="utf-8")
    base.chmod(0o755)
    venv_py = tmp_path / ".venv-parler" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.symlink_to(base)
    assert resolve_voice_design_python(project_root=tmp_path) == str(venv_py.absolute())
