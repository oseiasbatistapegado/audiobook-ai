"""Book and chapter models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Chapter(BaseModel):
    """A single chapter with stable id, title, and body text."""

    id: str
    title: str
    text: str = Field(min_length=1)


class Book(BaseModel):
    """A book composed of ordered chapters."""

    title: str
    chapters: list[Chapter] = Field(min_length=1)


class ExtractedPage(BaseModel):
    """Text extracted from one PDF page (1-based page number)."""

    page_number: int = Field(ge=1)
    text: str


class ExtractedPdf(BaseModel):
    """Full PDF extraction result including optional TOC entries."""

    title: str
    pages: list[ExtractedPage]
    toc: list[tuple[int, str, int]] = Field(
        default_factory=list,
        description="TOC entries as (level, title, page) from PyMuPDF.",
    )

    @property
    def full_text(self) -> str:
        """Concatenate page texts in order."""
        return "\n\n".join(page.text for page in self.pages)
