"""Audio merge tests with mocked ffmpeg / minimal WAV fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audiobook_ai.audio.merge import (
    AudioMergeError,
    FfmpegNotFoundError,
    ensure_ffmpeg,
    merge_segments,
)
from audiobook_ai.models.audio import AudioSegment

# Minimal RIFF/WAVE header-ish bytes for fixture segments
_MIN_WAV = b"RIFF$\x00\x00\x00WAVEfmt "


def test_ensure_ffmpeg_missing() -> None:
    with patch("audiobook_ai.audio.merge.shutil.which", return_value=None):
        with pytest.raises(FfmpegNotFoundError, match="ffmpeg"):
            ensure_ffmpeg()


def test_merge_preserves_order_and_calls_ffmpeg(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    segments = [
        AudioSegment(data=_MIN_WAV, chapter_id="ch-001", segment_index=0),
        AudioSegment(data=_MIN_WAV + b"2", chapter_id="ch-002", segment_index=0),
    ]
    output = tmp_path / "out" / "book.m4b"

    completed = MagicMock()
    completed.returncode = 0
    completed.stderr = ""

    with (
        patch("audiobook_ai.audio.merge.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("audiobook_ai.audio.merge.subprocess.run", return_value=completed) as run,
    ):
        result = merge_segments(segments, output, chapters_dir=chapters)

    assert result == output
    assert run.called
    command = run.call_args.args[0]
    assert command[0] == "/usr/bin/ffmpeg"
    assert str(output) in command
    # Intermediate files written in order under chapters/
    written = sorted(chapters.glob("*.wav"))
    assert len(written) == 2
    assert written[0].name.startswith("ch-001")
    assert written[1].name.startswith("ch-002")


def test_merge_rejects_empty() -> None:
    with patch("audiobook_ai.audio.merge.shutil.which", return_value="/usr/bin/ffmpeg"):
        with pytest.raises(AudioMergeError, match="No audio"):
            merge_segments([], Path("out/x.m4b"))
