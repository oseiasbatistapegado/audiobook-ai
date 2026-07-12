"""Split extracted PDF text into chapters (TOC → heuristics → single)."""

from __future__ import annotations

import re
from collections.abc import Sequence

from audiobook_ai.models.book import Book, Chapter, ExtractedPdf
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)

_CHAPTER_HEADING = re.compile(
    r"^(?:capítulo|capitulo|chapter)\s+(\d+|[ivxlcdm]+)\b[:.\s-]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_chapters(extracted: ExtractedPdf) -> Book:
    """Build a ``Book`` from extracted PDF content.

    Priority: useful TOC → heading heuristics → single chapter fallback.
    """
    toc_chapters = _chapters_from_toc(extracted)
    if toc_chapters is not None:
        logger.info("chapter split via TOC count=%s", len(toc_chapters))
        return Book(title=extracted.title, chapters=toc_chapters)

    heuristic = _chapters_from_headings(extracted.full_text)
    if heuristic is not None:
        logger.info("chapter split via headings count=%s", len(heuristic))
        return Book(title=extracted.title, chapters=heuristic)

    logger.info("chapter split fallback: single chapter")
    text = extracted.full_text.strip() or " "
    return Book(
        title=extracted.title,
        chapters=[Chapter(id="ch-001", title=extracted.title or "Chapter 1", text=text)],
    )


def _chapters_from_toc(extracted: ExtractedPdf) -> list[Chapter] | None:
    """Use TOC bookmarks when they yield at least two chapter ranges."""
    useful = _filter_toc(extracted.toc)
    if len(useful) < 2:
        return None

    page_map = {page.page_number: page.text for page in extracted.pages}
    max_page = max(page_map) if page_map else 0
    chapters: list[Chapter] = []

    for index, (_level, title, start_page) in enumerate(useful):
        end_page = useful[index + 1][2] - 1 if index + 1 < len(useful) else max_page
        texts = [
            page_map[page_num]
            for page_num in range(start_page, end_page + 1)
            if page_num in page_map
        ]
        body = "\n\n".join(texts).strip()
        if not body:
            continue
        chapters.append(
            Chapter(
                id=f"ch-{index + 1:03d}",
                title=title.strip() or f"Chapter {index + 1}",
                text=body,
            )
        )

    return chapters if len(chapters) >= 2 else None


def _filter_toc(
    toc: Sequence[tuple[int, str, int]],
) -> list[tuple[int, str, int]]:
    """Keep top-level-ish TOC entries with positive page numbers."""
    if not toc:
        return []
    min_level = min(entry[0] for entry in toc)
    filtered = [
        (level, title, page)
        for level, title, page in toc
        if level <= min_level + 1 and page >= 1 and title.strip()
    ]
    return filtered


def _chapters_from_headings(full_text: str) -> list[Chapter] | None:
    """Split on Capítulo/Chapter headings when multiple matches exist."""
    matches = list(_CHAPTER_HEADING.finditer(full_text))
    if len(matches) < 2:
        return None

    chapters: list[Chapter] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(full_text)
        body = full_text[start:end].strip()
        if not body:
            continue
        suffix = match.group(2).strip()
        number = match.group(1)
        title = suffix or f"Chapter {number}"
        chapters.append(Chapter(id=f"ch-{index + 1:03d}", title=title, text=body))

    return chapters if len(chapters) >= 2 else None
