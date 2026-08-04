"""Pipeline package for audiobook generation.

Re-exports the core pipeline logic (previously ``pipeline.py``) and
monkeypatchable symbols like ``PdfExtractor`` and ``merge_segments``.
"""

from __future__ import annotations

from audiobook_ai.extractors.pdf import PdfExtractor
from audiobook_ai.pipeline.core import (
    LifecycleManager,
    build_guardian,
    run_generate,
)
from audiobook_ai.pipeline.async_loop import AsyncPipelineRunner

# merge_segments is defined in audio.merge but was previously re-exported
# from pipeline.py's namespace — keep the import here so monkeypatches work.
from audiobook_ai.audio.merge import merge_segments

__all__ = [
    "run_generate",
    "AsyncPipelineRunner",
    "PdfExtractor",
    "merge_segments",
    "LifecycleManager",
    "build_guardian",
]
