"""Early dependency checks before the heavy generate pipeline."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from typing import Any, Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from audiobook_ai import config
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

TTS_INSTALL_HINT = (
    "Install TTS runtime with:\n"
    "  # ROCm torch first, then:\n"
    "  uv sync --extra tts-qwen\n"
    'Then verify: uv run python -c "import torch; import qwen_tts"'
)

PARLER_DAC_HINT = (
    "Install Voice Design (Parler) in an *isolated* venv "
    "(transformers==4.46.1; incompatible with qwen-tts 4.57.3):\n"
    "  bash scripts/bootstrap_parler_venv.sh\n"
    "  export AUDIOBOOK_AI_VOICE_DESIGN_PYTHON=.venv-parler/bin/python\n"
    f"DAC package: {config.DAC_PACKAGE}=={config.DAC_VERSION} "
    "(no fish-speech required)."
)

VOICE_DESIGN_RUNTIME_HINT = (
    "Parler Voice Design requires transformers==4.46.1 in a separate interpreter.\n"
    "  bash scripts/bootstrap_parler_venv.sh\n"
    "  export AUDIOBOOK_AI_VOICE_DESIGN_PYTHON=$PWD/.venv-parler/bin/python"
)

FFMPEG_HINT = (
    "ffmpeg not found on PATH. Enter the project env with "
    "`direnv allow` / `direnv reload` (or `nix develop`) so flake.nix provides ffmpeg, "
    "or install ffmpeg system-wide."
)

LLAMA_SERVER_HINT = (
    "llama-server not found on PATH. Install llama.cpp binaries "
    "(e.g. `nix develop -c pip install llama-cpp-python` or from your Nix env). "
    "Start with: llama-server --model <path/to/model.gguf> --port 8080 --jinja"
)


class _HTTPFetcher(Protocol):
    """Minimal surface for HTTP GET requests (mockable)."""

    def get(self, url: str, **kwargs: Any) -> Any: ...
    """Raised when a generate preflight check fails."""


class PreflightError(RuntimeError):
    """Raised when a generate preflight check fails."""


def run_preflight(
    *,
    llama_host: str,
    model: str,
    check_tts_imports: bool = True,
    check_parler_dac: bool = False,
    check_voice_design_runtime: bool = False,
    which: Callable[[str], str | None] | None = None,
    import_modules: Callable[[Sequence[str]], None] | None = None,
) -> None:
    """Validate ffmpeg, LLM reachability/model, and optional TTS imports.

    Raises ``PreflightError`` with an actionable message on the first failure.
    Does not download model weights.
    """
    check_ffmpeg(which=which)
    check_llama_server(
        llama_host=llama_host,
        model=model,
        check_llama_bin=which is not None or True,
    )
    if check_tts_imports:
        check_tts_python_imports(import_modules=import_modules)
    if check_parler_dac:
        check_parler_dac_imports(import_modules=import_modules)
    if check_voice_design_runtime:
        check_voice_design_python()
    logger.info(
        "preflight ok ffmpeg=yes backend=llama-server host=%s model=%s tts_imports=%s "
        "parler_dac=%s voice_design_runtime=%s",
        llama_host,
        model,
        check_tts_imports,
        check_parler_dac,
        check_voice_design_runtime,
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


def check_llama_server(
    *,
    llama_host: str,
    model: str,
    check_llama_bin: bool = True,
    timeout_s: float = 10.0,
) -> None:
    """Ensure the llama-server host is reachable and responding.

    llama-server exposes ``GET /health`` (200 OK) for availability checking
    and ``GET /v1/models`` for listing loaded models.
    """
    if check_llama_bin:
        # llama-server binary check is deferred — the server must already be running
        # (pipeline.py starts it via Popen before the first chapter).
        pass
    try:
        names = _fetch_llama_server_models(llama_host, timeout_s)
    except PreflightError:
        raise
    except Exception as exc:
        raise PreflightError(
            f"llama-server host is not reachable at {llama_host!r}: {exc}. "
            "Start llama-server (e.g. `llama-server --model <path> --port 8080 --jinja`) "
            "and confirm --llama-host / LLAMA_HOST."
        ) from exc

    # For llama-server, we accept any running server (model path is provided at start time).
    # We still log a warning if the requested model doesn't match.
    if not _model_is_available(model, names):
        logger.warning(
            "llama-server running but model %r not listed; "
            "the server may be loaded with a different model. "
            "Proceeding — the pipeline will start/verify the server.",
            model,
        )


def check_tts_python_imports(
    *,
    import_modules: Callable[[Sequence[str]], None] | None = None,
) -> None:
    """Ensure ``torch`` and ``qwen_tts`` import without downloading weights."""
    importer = import_modules or _import_modules
    try:
        importer(("torch", "qwen_tts"))
    except Exception as exc:
        raise PreflightError(
            f"TTS Python packages are not importable ({exc}).\n{TTS_INSTALL_HINT}"
        ) from exc


def check_parler_dac_imports(
    *,
    import_modules: Callable[[Sequence[str]], None] | None = None,
) -> None:
    """Ensure Parler decode deps (DAC) import without fish-speech.

    Prefer running this check inside the Voice Design interpreter; the
    orchestrator process may not have Parler installed.
    """
    importer = import_modules or _import_modules
    try:
        importer(("dac",))
    except Exception as exc:
        raise PreflightError(
            f"Parler DAC decode package is not importable ({exc}).\n{PARLER_DAC_HINT}"
        ) from exc


def check_voice_design_python() -> None:
    """Ensure an isolated Parler interpreter is configured and runnable."""
    from audiobook_ai.gpu.runtimes import (
        ENV_VOICE_DESIGN_PYTHON,
        resolve_voice_design_python,
        worker_env,
    )
    import subprocess

    python = resolve_voice_design_python()
    try:
        completed = subprocess.run(
            [
                python,
                "-c",
                "import transformers; from parler_tts import ParlerTTSForConditionalGeneration; "
                "assert transformers.__version__.startswith('4.46.1'), transformers.__version__",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=worker_env(),
        )
    except OSError as exc:
        raise PreflightError(
            f"Cannot execute Voice Design python {python!r}: {exc}.\n"
            f"{VOICE_DESIGN_RUNTIME_HINT}"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PreflightError(
            f"Voice Design runtime check failed ({python}): {detail}\n"
            f"{VOICE_DESIGN_RUNTIME_HINT}\n"
            f"(env override: {ENV_VOICE_DESIGN_PYTHON})"
        )


def _import_modules(names: Sequence[str]) -> None:
    import importlib

    for name in names:
        importlib.import_module(name)


def _fetch_llama_server_models(host: str, timeout_s: float) -> list[str]:
    """Fetch model list from llama-server via GET /v1/models."""
    import httpx

    base = host.rstrip("/")
    url = f"{base}/v1/models"
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
            response = client.get(url)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
    except httpx.HTTPStatusError as exc:
        raise PreflightError(
            f"llama-server at {host!r} returned HTTP {exc.response.status_code}: {exc}"
        ) from exc
    except httpx.ConnectError as exc:
        raise PreflightError(
            f"Cannot connect to llama-server at {host!r}: {exc}. "
            "Start llama-server and retry."
        ) from exc
    except TimeoutError as exc:
        raise PreflightError(
            f"Timed out contacting llama-server at {host!r}. "
            "Start llama-server and retry."
        ) from exc

    models = data.get("data") or data.get("models") or []
    names: list[str] = []
    for item in models:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


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
