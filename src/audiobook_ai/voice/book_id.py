"""Stable audiobook id from input file content (not path)."""

from __future__ import annotations

import hashlib
from pathlib import Path

# BLAKE2b-128 → 32 hex chars. Rename/move of the source MUST NOT change this.
BOOK_ID_DIGEST_SIZE = 16


def compute_book_id(source: Path | str | bytes) -> str:
    """Return BLAKE2b-128 hex digest of the input bytes.

    ``source`` may be a filesystem path (file is read) or raw bytes.
    """
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        path = Path(source)
        data = path.read_bytes()
    return hashlib.blake2b(data, digest_size=BOOK_ID_DIGEST_SIZE).hexdigest()
