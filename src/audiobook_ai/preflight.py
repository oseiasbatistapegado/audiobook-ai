"""Early dependency checks before the heavy generate pipeline."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

TTS_INSTALL_HINT = (
    "Install TTS runtime with:\n"
    "  uv sync --extra tts-fish\n"
    "  uv pip install --no-deps "
    '"fish-speech @ git+https://github.com/fishaudio/fish-speech@v2.0.0-beta"\n'
    'Then verify: uv run python -c "import torch; import fish_speech"'
)

FFMPEG_HINT = (
    "ffmpeg not found on PATH. Enter the project env with "
    "`direnv allow` / `direnv reload` (or `nix develop`) so flake.nix provides ffmpeg, "
    "or install ffmpeg system-wide."
)


class PreflightError(RuntimeError):
    """Raised when a generate preflight check fails."""


def run_preflight(
    *,
    ollama_host: str,
    model: str,
    check_tts_imports: bool = True,
    which: Callable[[str], str | None] | None = None,
    list_ollama_models: Callable[[str], Sequence[str]] | None = None,
    import_modules: Callable[[Sequence[str]], None] | None = None,
) -> None:
    """Validate ffmpeg, Ollama reachability/model, and optional TTS imports.

    Raises ``PreflightError`` with an actionable message on the first failure.
    Does not download model weights.
    """
    check_ffmpeg(which=which)
    check_ollama(ollama_host=ollama_host, model=model, list_models=list_ollama_models)
    if check_tts_imports:
        check_tts_python_imports(import_modules=import_modules)
    logger.info(
        "preflight ok ffmpeg=yes ollama=%s model=%s tts_imports=%s",
        ollama_host,
        model,
        check_tts_imports,
    )


def check_ffmpeg(*, which: Callable[[str], str | None] | None = None) -> None:
    """Ensure ``ffmpeg`` is available on PATH."""
    resolver = which or shutil.which
    if resolver("ffmpeg") is None:
        raise PreflightError(FFMPEG_HINT)


def check_ollama(
    *,
    ollama_host: str,
    model: str,
    list_models: Callable[[str], Sequence[str]] | None = None,
    timeout_s: float = 5.0,
) -> None:
    """Ensure the Ollama host is reachable and ``model`` is installed."""
    fetcher = list_models or (lambda host: _fetch_ollama_model_names(host, timeout_s))
    try:
        names = list(fetcher(ollama_host))
    except PreflightError:
        raise
    except Exception as exc:
        raise PreflightError(
            f"Ollama host is not reachable at {ollama_host!r}: {exc}. "
            "Start Ollama (e.g. `ollama serve`) and confirm --ollama-host / OLLAMA_HOST."
        ) from exc

    if not _model_is_available(model, names):
        raise PreflightError(
            f"Ollama model {model!r} is not installed on {ollama_host!r}. "
            f"Install it with: ollama pull {model}"
        )


def check_tts_python_imports(
    *,
    import_modules: Callable[[Sequence[str]], None] | None = None,
) -> None:
    """Ensure ``torch`` and ``fish_speech`` import without downloading weights."""
    importer = import_modules or _import_modules
    try:
        importer(("torch", "fish_speech"))
    except Exception as exc:
        raise PreflightError(
            f"TTS Python packages are not importable ({exc}).\n{TTS_INSTALL_HINT}"
        ) from exc


def _import_modules(names: Sequence[str]) -> None:
    import importlib

    for name in names:
        importlib.import_module(name)


def _fetch_ollama_model_names(host: str, timeout_s: float) -> list[str]:
    base = host.rstrip("/")
    url = f"{base}/api/tags"
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 — local Ollama
            payload = response.read()
    except URLError as exc:
        raise PreflightError(
            f"Ollama host is not reachable at {host!r}: {exc.reason}. "
            "Start Ollama (e.g. `ollama serve`) and confirm --ollama-host / OLLAMA_HOST."
        ) from exc
    except TimeoutError as exc:
        raise PreflightError(
            f"Timed out contacting Ollama at {host!r}. "
            "Start Ollama and retry, or check --ollama-host."
        ) from exc

    import json

    try:
        data: dict[str, Any] = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreflightError(
            f"Ollama at {host!r} returned an invalid /api/tags payload: {exc}"
        ) from exc

    models = data.get("models") or []
    names: list[str] = []
    for item in models:
        if isinstance(item, dict):
            name = item.get("name") or item.get("model")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def _model_is_available(requested: str, available: Sequence[str]) -> bool:
    """Match Ollama model names allowing tag-less aliases (``qwen3`` ≈ ``qwen3:latest``)."""
    requested = requested.strip()
    if not requested:
        return False
    names = {name.strip() for name in available if name and name.strip()}
    if requested in names:
        return True
    return ":" not in requested and f"{requested}:latest" in names

