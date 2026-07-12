"""TextExtractor interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from audiobook_ai.models.book import ExtractedPdf


class TextExtractor(ABC):
    """Extract typed text content from a document."""

    @abstractmethod
    def extract(self, path: Path) -> ExtractedPdf:
        """Extract text from ``path`` into an ``ExtractedPdf`` model."""
