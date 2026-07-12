"""Text extraction interfaces and PDF implementation."""

from audiobook_ai.extractors.base import TextExtractor
from audiobook_ai.extractors.pdf import PdfExtractor

__all__ = ["PdfExtractor", "TextExtractor"]
