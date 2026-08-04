"""Normalize extracted PDF/plain text before chapter parse / LLM."""

from __future__ import annotations

import re

# Letter (any script word char except digits/underscore) immediately across a newline.
_MIDWORD_LINEBREAK = re.compile(r"([^\W\d_])\n([^\W\d_])", re.UNICODE)


def repair_midword_linebreaks(text: str) -> str:
    """Join words split across a single newline (common PDF artifact).

    Example: ``ELI\\nTE`` → ``ELITE``. Paragraph breaks (``\\n\\n``) are preserved
    because they are not ``letter\\nletter``. Soft wraps with a trailing space
    (``school \\nwith``) are also left alone.
    """
    if not text or "\n" not in text:
        return text
    prev = None
    out = text
    # Repeat for chains like A\\nB\\nC.
    while prev != out:
        prev = out
        out = _MIDWORD_LINEBREAK.sub(r"\1\2", out)
    return out
