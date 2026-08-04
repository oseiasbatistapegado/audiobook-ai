"""Central ModelManager: ensure / get pinned weights (neutral registry)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from audiobook_ai.utils.logging import get_logger
from audiobook_ai.weights.cache import download_lock, model_dir, resolve_cache_root
from audiobook_ai.weights.definition import PinnedModel
from audiobook_ai.weights.qwen3_tts import QWEN3_TTS_ID, QWEN3_TTS_MODEL

logger = get_logger(__name__)

ProgressCallback = Callable[[str, float | None], None]

_AUTH_HINT = (
    "Hugging Face download failed. "
    "Run `hf auth login` if the repo requires auth, check network access, then retry."
)


@dataclass(frozen=True, slots=True)
class ModelHandle:
    """Resolved on-disk model location."""

    logical_id: str
    path: Path
    repository: str
    revision: str


def default_model_registry() -> dict[str, PinnedModel]:
    """Product weight registry (Qwen3-TTS only)."""
    return {QWEN3_TTS_MODEL.logical_id: QWEN3_TTS_MODEL}


class ModelManager:
    """Ensure Hugging Face weights are downloaded, validated, and reusable."""

    def __init__(
        self,
        *,
        cache_dir: Path | str | None = None,
        models: Iterable[PinnedModel] | None = None,
        hub_download: Callable[..., Path] | None = None,
    ) -> None:
        self.cache_root = resolve_cache_root(cache_dir)
        self._hub_download = hub_download
        registry_models = (
            list(models) if models is not None else list(default_model_registry().values())
        )
        self._registry: dict[str, PinnedModel] = {
            m.logical_id: m for m in registry_models
        }

    def get_model(self, logical_id: str = QWEN3_TTS_ID) -> ModelHandle:
        """Return a handle for an already-ensured model; raises if not ready."""
        definition = self._require_definition(logical_id)
        path = model_dir(self.cache_root, logical_id)
        missing = self._missing_required(path, definition.required_files)
        if missing:
            raise FileNotFoundError(
                f"Model {logical_id!r} is not ready under {path}: "
                f"missing {', '.join(missing)}. Call ensure_model first."
            )
        return ModelHandle(
            logical_id=logical_id,
            path=path,
            repository=definition.repository,
            revision=definition.revision,
        )

    def ensure_model(
        self,
        logical_id: str = QWEN3_TTS_ID,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> ModelHandle:
        """Download (if needed) and validate required files; reuse intact cache."""
        definition = self._require_definition(logical_id)
        if definition.revision.strip().lower() == "main":
            raise ValueError(
                f"Refusing to download {logical_id!r} from floating revision 'main'"
            )

        path = model_dir(self.cache_root, logical_id)
        path.mkdir(parents=True, exist_ok=True)

        with download_lock(path):
            missing = self._missing_required(path, definition.required_files)
            if not missing:
                logger.info(
                    "model-ensure id=%s status=cache-hit path=%s revision=%s",
                    logical_id,
                    path,
                    definition.revision,
                )
                self._notify(progress_callback, "cache-hit", 1.0)
                return ModelHandle(
                    logical_id=logical_id,
                    path=path,
                    repository=definition.repository,
                    revision=definition.revision,
                )

            logger.info(
                "model-ensure id=%s status=download missing=%s repo=%s revision=%s",
                logical_id,
                missing,
                definition.repository,
                definition.revision,
            )
            self._notify(progress_callback, "download-start", 0.0)
            try:
                self._download(definition, path, progress_callback=progress_callback)
            except Exception as exc:
                raise _wrap_hub_error(exc, definition) from exc

            still_missing = self._missing_required(path, definition.required_files)
            if still_missing:
                raise RuntimeError(
                    f"Model {logical_id!r} incomplete after download under {path}: "
                    f"missing {', '.join(still_missing)}"
                )

            self._notify(progress_callback, "download-complete", 1.0)
            return ModelHandle(
                logical_id=logical_id,
                path=path,
                repository=definition.repository,
                revision=definition.revision,
            )

    def _download(
        self,
        definition: PinnedModel,
        dest: Path,
        *,
        progress_callback: ProgressCallback | None,
    ) -> None:
        download = self._hub_download or _default_hub_download
        download(
            repository=definition.repository,
            revision=definition.revision,
            local_dir=dest,
            allow_patterns=list(definition.required_files),
            progress_callback=progress_callback,
        )

    def _require_definition(self, logical_id: str) -> PinnedModel:
        try:
            return self._registry[logical_id]
        except KeyError as exc:
            raise KeyError(
                f"Unknown model id {logical_id!r}. "
                f"Known: {', '.join(sorted(self._registry))}"
            ) from exc

    @staticmethod
    def _missing_required(path: Path, required: tuple[str, ...]) -> list[str]:
        missing: list[str] = []
        for name in required:
            candidate = path / name
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                missing.append(name)
        return missing

    @staticmethod
    def _notify(
        callback: ProgressCallback | None,
        message: str,
        fraction: float | None,
    ) -> None:
        if callback is not None:
            callback(message, fraction)


def _wrap_hub_error(exc: BaseException, definition: PinnedModel) -> BaseException:
    """Attach an actionable hint for auth / gated Hugging Face failures."""
    text = f"{type(exc).__name__}: {exc}".lower()
    gated = any(
        token in text
        for token in (
            "gated",
            "401",
            "403",
            "unauthorized",
            "restricted",
            "cannot access",
            "access to model",
        )
    )
    if not gated:
        return exc if isinstance(exc, Exception) else RuntimeError(str(exc))
    message = (
        f"Failed to download weights {definition.logical_id!r} "
        f"({definition.repository}@{definition.revision}): {_AUTH_HINT} "
        f"Original error: {exc}"
    )
    return RuntimeError(message)


def _default_hub_download(
    *,
    repository: str,
    revision: str,
    local_dir: Path,
    allow_patterns: list[str],
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Download via Hugging Face Hub Python API only (no subprocess/CLI)."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ImportError(
            "huggingface_hub is required for model download. "
            "Install project deps (uv sync) or the tts-qwen extra."
        ) from exc

    if revision.strip().lower() == "main":
        raise ValueError("Refusing huggingface download with revision='main'")

    if progress_callback is not None:
        progress_callback("download", 0.0)

    result = snapshot_download(
        repo_id=repository,
        revision=revision,
        local_dir=str(local_dir),
        allow_patterns=allow_patterns,
    )
    if progress_callback is not None:
        progress_callback("download", 1.0)
    return Path(result)
