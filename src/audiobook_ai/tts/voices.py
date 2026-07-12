"""Resolve packaged, registry, and user-provided Fish Speech voice reference paths."""

from __future__ import annotations

import json
from pathlib import Path

from audiobook_ai import config
from audiobook_ai.models.voice import CANONICAL_VOICE_LANGUAGE
from audiobook_ai.utils.logging import get_logger
from audiobook_ai.weights.cache import resolve_cache_root

logger = get_logger(__name__)

DEFAULT_VOICE_ID = config.DEFAULT_VOICE_ID
_VOICE_REF_NAMES = ("reference.wav", "reference.lab", "reference.txt")


def project_assets_voices_root() -> Path:
    """Return ``assets/voices`` at the repository / project root when present."""
    # src/audiobook_ai/tts/voices.py → parents: tts, audiobook_ai, src, repo
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "assets" / "voices"


def packaged_voice_dir(voice_id: str) -> Path | None:
    """Return the packaged voice directory if it exists and looks complete."""
    candidate = project_assets_voices_root() / voice_id
    if _is_voice_dir(candidate):
        return candidate
    return None


def registry_voice_dir(
    voice_id: str,
    *,
    book_id: str | None = None,
    cache_root: Path | str | None = None,
) -> Path | None:
    """Return ``<cache-root>/voices/<book_id>/<voice_id>/`` when present.

    If ``book_id`` is omitted, also try legacy flat ``voices/<voice_id>/`` for
    older caches (read-only compatibility).
    """
    root = resolve_cache_root(cache_root)
    voices = root / config.VOICES_CACHE_SUBDIR
    if book_id:
        candidate = voices / book_id / voice_id
        if _is_voice_dir(candidate):
            return candidate
        return None
    # Legacy flat layout
    candidate = voices / voice_id
    if _is_voice_dir(candidate):
        return candidate
    return None


def user_voice_dir(voice_id: str, *, cwd: Path | None = None) -> Path | None:
    """Return ``./references/<voice_id>`` when the user provided an override."""
    root = cwd if cwd is not None else Path.cwd()
    candidate = root / "references" / voice_id
    if _is_voice_dir(candidate):
        return candidate
    return None


def voice_language(voice_dir: Path) -> str | None:
    """Read ``language`` from metadata.json when present."""
    meta_path = voice_dir / "metadata.json"
    if not meta_path.is_file():
        return None
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    language = raw.get("language")
    return str(language) if language is not None else None


def is_pt_br_voice(voice_dir: Path, *, require_metadata: bool = True) -> bool:
    """Return True when the voice directory is eligible as automatic pt-BR."""
    if not _is_voice_dir(voice_dir):
        return False
    language = voice_language(voice_dir)
    if language == CANONICAL_VOICE_LANGUAGE:
        return True
    if language is None and not require_metadata:
        return True
    return False


def resolve_voice_dir(
    voice_id: str,
    *,
    references_dir: Path | None = None,
    cwd: Path | None = None,
    cache_root: Path | str | None = None,
    book_id: str | None = None,
    require_pt_br: bool = True,
    allow_user_without_metadata: bool = True,
) -> tuple[str, Path]:
    """Resolve ``voice_id`` to ``(effective_id, voice_directory)``.

    Priority:
    1. Explicit ``references_dir`` injection (tests / callers)
    2. User ``./references/<id>/`` override when present for that id
    3. Registry cache ``<cache-root>/voices/<book_id>/<id>/``
    4. Packaged ``assets/voices/<id>/`` (dev/override only — not generative success)
    5. Optional documented fallback to packaged narrator **only if pt-BR**
    """
    requested = (voice_id or DEFAULT_VOICE_ID).strip() or DEFAULT_VOICE_ID

    if references_dir is not None:
        injected = _voice_under_references_root(references_dir, requested)
        if injected is not None:
            _assert_language_ok(
                injected,
                requested,
                require_pt_br=require_pt_br,
                allow_missing_metadata=allow_user_without_metadata,
            )
            return requested, injected
        if _is_voice_dir(references_dir):
            _assert_language_ok(
                references_dir,
                requested,
                require_pt_br=require_pt_br,
                allow_missing_metadata=allow_user_without_metadata,
            )
            return requested, references_dir

    user = user_voice_dir(requested, cwd=cwd)
    if user is not None:
        _assert_language_ok(
            user,
            requested,
            require_pt_br=require_pt_br,
            allow_missing_metadata=allow_user_without_metadata,
        )
        return requested, user

    registry = registry_voice_dir(
        requested, book_id=book_id, cache_root=cache_root
    )
    if registry is not None:
        _assert_language_ok(
            registry,
            requested,
            require_pt_br=require_pt_br,
            allow_missing_metadata=False,
        )
        return requested, registry

    packaged = packaged_voice_dir(requested)
    if packaged is not None:
        _assert_language_ok(
            packaged,
            requested,
            require_pt_br=require_pt_br,
            allow_missing_metadata=False,
        )
        return requested, packaged

    if requested != DEFAULT_VOICE_ID:
        for candidate in (
            user_voice_dir(DEFAULT_VOICE_ID, cwd=cwd),
            registry_voice_dir(
                DEFAULT_VOICE_ID, book_id=book_id, cache_root=cache_root
            ),
            packaged_voice_dir(DEFAULT_VOICE_ID),
        ):
            if candidate is None:
                continue
            if require_pt_br and not is_pt_br_voice(
                candidate, require_metadata=not allow_user_without_metadata
            ):
                continue
            logger.warning(
                "voice_id=%s has no pt-BR reference folder; falling back to %s",
                requested,
                DEFAULT_VOICE_ID,
            )
            return DEFAULT_VOICE_ID, candidate

    raise FileNotFoundError(
        f"No pt-BR Fish Speech voice references found for voice_id={requested!r}. "
        f"Expected registry under <cache>/voices/<book_id>/{requested}/, packaged "
        f"assets at {project_assets_voices_root() / DEFAULT_VOICE_ID}, "
        f"or user override under ./references/{requested}/"
    )


def _assert_language_ok(
    voice_dir: Path,
    voice_id: str,
    *,
    require_pt_br: bool,
    allow_missing_metadata: bool,
) -> None:
    if not require_pt_br:
        return
    if is_pt_br_voice(voice_dir, require_metadata=not allow_missing_metadata):
        return
    language = voice_language(voice_dir)
    raise FileNotFoundError(
        f"Voice {voice_id!r} at {voice_dir} is not eligible as pt-BR "
        f"(language={language!r}). Automatic flow rejects non-pt-BR references."
    )


def _voice_under_references_root(references_dir: Path, voice_id: str) -> Path | None:
    """Interpret ``references_dir`` as a references folder or its parent."""
    if references_dir.name == "references":
        candidate = references_dir / voice_id
    else:
        # Parent of references/, or a root that contains references/
        nested = references_dir / "references" / voice_id
        if _is_voice_dir(nested):
            return nested
        candidate = references_dir / voice_id
    if _is_voice_dir(candidate):
        return candidate
    return None


def _is_voice_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "reference.wav").is_file():
        return True
    return any((path / name).is_file() for name in _VOICE_REF_NAMES) or any(
        path.glob("*.wav")
    )
