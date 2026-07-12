"""Concatenate audio segments with ffmpeg (default M4B)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from audiobook_ai.models.audio import AudioSegment
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)


class FfmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg is missing from PATH."""


class AudioMergeError(RuntimeError):
    """Raised when ffmpeg merge fails."""


def ensure_ffmpeg() -> str:
    """Return the ffmpeg executable path or raise a clear error."""
    path = shutil.which("ffmpeg")
    if path is None:
        raise FfmpegNotFoundError(
            "ffmpeg not found in PATH. Enter the Nix/direnv shell "
            "(`direnv allow` / `direnv reload`) or install ffmpeg."
        )
    return path


def merge_segments(
    segments: list[AudioSegment],
    output_path: Path,
    *,
    chapters_dir: Path | None = None,
) -> Path:
    """Merge ordered segments into ``output_path`` (``.m4b`` or ``.mp3``)."""
    if not segments:
        raise AudioMergeError("No audio segments to merge")

    ffmpeg = ensure_ffmpeg()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    suffix = output_path.suffix.lower()
    if suffix not in {".m4b", ".mp3"}:
        raise AudioMergeError(
            f"Unsupported output extension {suffix!r}; use .m4b (default) or .mp3"
        )

    with tempfile.TemporaryDirectory(prefix="audiobook-merge-") as tmp:
        tmp_dir = Path(tmp)
        input_files = _materialize_segments(segments, tmp_dir, chapters_dir)
        list_file = tmp_dir / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{path.resolve()}'" for path in input_files) + "\n",
            encoding="utf-8",
        )

        codec_args = _codec_args(suffix)
        command = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            *codec_args,
            str(output_path),
        ]
        logger.info(
            "merging audio segments=%s output=%s format=%s",
            len(input_files),
            output_path,
            suffix,
        )
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise AudioMergeError(
                f"ffmpeg merge failed (code={completed.returncode}): "
                f"{completed.stderr[-500:]}"
            )

    return output_path


def _codec_args(suffix: str) -> list[str]:
    if suffix == ".mp3":
        return ["-c:a", "libmp3lame", "-q:a", "2"]
    # M4B / AAC audiobook container
    return ["-c:a", "aac", "-b:a", "128k", "-f", "mp4", "-movflags", "+faststart"]


def _materialize_segments(
    segments: list[AudioSegment],
    tmp_dir: Path,
    chapters_dir: Path | None,
) -> list[Path]:
    files: list[Path] = []
    for index, segment in enumerate(segments):
        if segment.path is not None and segment.path.is_file():
            files.append(segment.path)
            continue
        if segment.data is None:
            raise AudioMergeError(f"Segment {index} has neither path nor data")

        target_dir = chapters_dir if chapters_dir is not None else tmp_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        chapter = segment.chapter_id or "chapter"
        seg_index = segment.segment_index if segment.segment_index is not None else index
        path = target_dir / f"{chapter}_{seg_index:04d}.{segment.format}"
        path.write_bytes(segment.data)
        files.append(path)
    return files
