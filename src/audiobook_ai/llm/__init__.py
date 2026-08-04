"""LLM backends for chapter interpretation."""

from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.llm.llama_cpp_backend import LlamaCppBackend

__all__ = ["LLMBackend", "LlamaCppBackend"]
