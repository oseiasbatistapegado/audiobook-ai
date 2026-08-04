"""Book-scoped Pass A (interpret) progress for resume."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from audiobook_ai import config
from audiobook_ai.state.manifest import (
    SpeechManifest,
    is_chunk_valid,
    load_manifest,
)
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)


class InterpretProgress(BaseModel):
    """Chapters whose Pass A (interpret) and TTS (synthesize) completed
    successfully under a given LLM policy."""

    version: int = 1
    interpreted_chapter_ids: list[str] = Field(default_factory=list)
    synthesized_chapter_ids: list[str] = Field(default_factory=list)
    model: str = ""
    adaptation_policy_version: str = ""
    diarization_policy_version: str = ""

    def matches_execution(
        self,
        *,
        model: str,
        adaptation_policy_version: str | None = None,
        diarization_policy_version: str | None = None,
    ) -> bool:
        """Return True when stored metadata matches the current generate run."""
        adapt = (
            config.LLM_ADAPTATION_POLICY_VERSION
            if adaptation_policy_version is None
            else adaptation_policy_version
        )
        diar = (
            config.LLM_DIARIZATION_POLICY_VERSION
            if diarization_policy_version is None
            else diarization_policy_version
        )
        return (
            self.model == model
            and self.adaptation_policy_version == adapt
            and self.diarization_policy_version == diar
        )

    def contains(self, chapter_id: str) -> bool:
        return chapter_id in self.interpreted_chapter_ids

    def is_synthesized(self, chapter_id: str) -> bool:
        """Return True when the chapter has been fully synthesized (TTS done)."""
        return chapter_id in self.synthesized_chapter_ids


def empty_progress(*, model: str) -> InterpretProgress:
    """Fresh progress for the current model/policies."""
    return InterpretProgress(
        model=model,
        adaptation_policy_version=config.LLM_ADAPTATION_POLICY_VERSION,
        diarization_policy_version=config.LLM_DIARIZATION_POLICY_VERSION,
    )


def load_interpret_progress(path: Path) -> InterpretProgress | None:
    """Load progress from disk, or ``None`` if missing/invalid."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return InterpretProgress.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("ignoring invalid interpret progress path=%s error=%s", path, exc)
        return None


def save_interpret_progress(progress: InterpretProgress, path: Path) -> None:
    """Atomically write interpret progress JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = progress.model_dump_json(indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".interpret-progress-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    logger.info(
        "saved interpret progress path=%s chapters=%s",
        path,
        len(progress.interpreted_chapter_ids),
    )


def mark_chapter_interpreted(progress: InterpretProgress, chapter_id: str) -> InterpretProgress:
    """Return a copy with ``chapter_id`` appended to interpreted list if not present."""
    if chapter_id in progress.interpreted_chapter_ids:
        return progress
    ids = [*progress.interpreted_chapter_ids, chapter_id]
    return progress.model_copy(update={"interpreted_chapter_ids": ids})


def mark_chapter_synthesized(progress: InterpretProgress, chapter_id: str) -> InterpretProgress:
    """Return a copy with ``chapter_id`` appended to synthesized list if not present."""
    if chapter_id in progress.synthesized_chapter_ids:
        return progress
    ids = [*progress.synthesized_chapter_ids, chapter_id]
    return progress.model_copy(update={"synthesized_chapter_ids": ids})


def bootstrap_interpreted_ids(
    chapter_ids_in_book_order: list[str],
    manifest: SpeechManifest,
) -> list[str]:
    """Infer completed chapters from manifest, excluding the last present id.

    The last chapter_id that appears in the manifest is treated as potentially
    partial (crash mid-Pass-A) and remains eligible for re-interpretation.
    """
    present: list[str] = []
    seen: set[str] = set()
    manifest_chapter_ids = {
        str(entry.metadata.get("chapter_id") or "")
        for entry in manifest.chunks
        if entry.metadata.get("chapter_id")
    }
    for chapter_id in chapter_ids_in_book_order:
        if chapter_id in manifest_chapter_ids and chapter_id not in seen:
            present.append(chapter_id)
            seen.add(chapter_id)
    if len(present) <= 1:
        return []
    return present[:-1]


def bootstrap_synthesized_ids(
    chapter_ids_in_book_order: list[str],
    manifest: SpeechManifest,
    book_root: Path,
) -> list[str]:
    """Infer fully synthesized chapters from manifest.

    A chapter is considered synthesized when ALL of its chunks have
    ``COMPLETED`` status and valid, non-empty audio files.
    """
    # Group chunks by chapter_id
    chapter_chunks: dict[str, list[ManifestChunkEntry]] = {}
    for entry in manifest.chunks:
        cid = str(entry.metadata.get("chapter_id") or "")
        if cid:
            chapter_chunks.setdefault(cid, []).append(entry)

    synthesized: list[str] = []
    for chapter_id in chapter_ids_in_book_order:
        if chapter_id not in chapter_chunks:
            continue
        chunks = chapter_chunks[chapter_id]
        if not chunks:
            continue
        all_valid = all(is_chunk_valid(c, book_root=book_root) for c in chunks)
        if all_valid:
            synthesized.append(chapter_id)

    return synthesized


def resolve_interpret_progress(
    path: Path,
    *,
    model: str,
    book_chapter_ids: list[str],
    manifest_path: Path | None = None,
    book_root: Path | None = None,
) -> InterpretProgress:
    """Load progress, invalidate on policy/model mismatch, or bootstrap from manifest."""
    loaded = load_interpret_progress(path)
    if loaded is not None:
        if loaded.matches_execution(model=model):
            return loaded
        logger.info(
            "interpret progress invalidated model/policy mismatch path=%s",
            path,
        )
        return empty_progress(model=model)

    progress = empty_progress(model=model)
    if manifest_path is not None and Path(manifest_path).is_file():
        try:
            manifest = load_manifest(manifest_path)
        except Exception as exc:
            logger.warning(
                "interpret bootstrap skipped; bad manifest path=%s error=%s",
                manifest_path,
                exc,
            )
            return progress

        # Bootstrap interpreted chapters (existing logic)
        bootstrapped_interpreted = bootstrap_interpreted_ids(book_chapter_ids, manifest)
        if bootstrapped_interpreted:
            progress = progress.model_copy(
                update={"interpreted_chapter_ids": bootstrapped_interpreted}
            )

        # Bootstrap synthesized chapters (TTS done)
        bootstrapped_synthesized: list[str] = []
        if book_root is not None:
            bootstrapped_synthesized = bootstrap_synthesized_ids(
                book_chapter_ids, manifest, Path(book_root)
            )
            if bootstrapped_synthesized:
                progress = progress.model_copy(
                    update={"synthesized_chapter_ids": bootstrapped_synthesized}
                )

        if bootstrapped_interpreted or bootstrapped_synthesized:
            save_interpret_progress(progress, path)
            logger.info(
                "interpret progress bootstrapped from manifest interpreted=%s synthesized=%s",
                bootstrapped_interpreted,
                bootstrapped_synthesized,
            )
    return progress
