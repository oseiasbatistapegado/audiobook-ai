"""PDF text extraction via PyMuPDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiobook_ai.extractors.base import TextExtractor
from audiobook_ai.models.book import ExtractedPage, ExtractedPdf
from audiobook_ai.parser.text_normalize import repair_midword_linebreaks
from audiobook_ai.utils.logging import get_logger

logger = get_logger(__name__)


class PdfExtractionError(RuntimeError):
    """Raised when a PDF cannot yield extractable text."""


class PdfExtractor(TextExtractor):
    """Extract selectable text from a PDF using PyMuPDF."""

    def extract(self, path: Path) -> ExtractedPdf:
        """Extract pages and TOC; fail clearly if no text is present."""
        import fitz

        pdf_path = Path(path)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        logger.info("extracting PDF path=%s", pdf_path)
        document = fitz.open(pdf_path)
        try:
            pages = self._extract_pages(document)
            if not any(page.text.strip() for page in pages):
                raise PdfExtractionError(
                    f"PDF has no extractable text (OCR is out of scope): {pdf_path}"
                )
            toc_raw = document.get_toc(simple=True)
            toc = [(int(level), str(title), int(page)) for level, title, page in toc_raw]
            title = (document.metadata or {}).get("title") or pdf_path.stem
            return ExtractedPdf(title=str(title), pages=pages, toc=toc)
        finally:
            document.close()

    def _extract_pages(self, document: Any) -> list[ExtractedPage]:
        pages: list[ExtractedPage] = []
        for index in range(document.page_count):
            page = document.load_page(index)
            text = repair_midword_linebreaks(page.get_text("text") or "")
            pages.append(ExtractedPage(page_number=index + 1, text=text))
        return pages
