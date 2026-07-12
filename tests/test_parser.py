"""Chapter parser tests with mocked TOC / headings."""

from __future__ import annotations

from audiobook_ai.models.book import ExtractedPage, ExtractedPdf
from audiobook_ai.parser.chapters import parse_chapters


def test_parse_from_toc() -> None:
    extracted = ExtractedPdf(
        title="Demo",
        pages=[
            ExtractedPage(page_number=1, text="Intro page one"),
            ExtractedPage(page_number=2, text="Chapter one body"),
            ExtractedPage(page_number=3, text="Chapter two body"),
        ],
        toc=[
            (1, "Chapter 1", 2),
            (1, "Chapter 2", 3),
        ],
    )
    book = parse_chapters(extracted)
    assert len(book.chapters) == 2
    assert book.chapters[0].title == "Chapter 1"
    assert "one body" in book.chapters[0].text
    assert "two body" in book.chapters[1].text


def test_parse_from_headings() -> None:
    text = (
        "Chapter 1 The Beginning\n"
        "Once there was a village.\n\n"
        "Chapter 2 The Road\n"
        "They left at dawn.\n"
    )
    extracted = ExtractedPdf(
        title="Road",
        pages=[ExtractedPage(page_number=1, text=text)],
        toc=[],
    )
    book = parse_chapters(extracted)
    assert len(book.chapters) == 2
    assert "village" in book.chapters[0].text
    assert "dawn" in book.chapters[1].text


def test_single_chapter_fallback() -> None:
    extracted = ExtractedPdf(
        title="Short",
        pages=[ExtractedPage(page_number=1, text="Just a short story without headings.")],
        toc=[],
    )
    book = parse_chapters(extracted)
    assert len(book.chapters) == 1
    assert "short story" in book.chapters[0].text
