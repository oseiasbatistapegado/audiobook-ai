"""LLM backends for chapter interpretation."""

from audiobook_ai.llm.base import LLMBackend
from audiobook_ai.llm.ollama_backend import OllamaBackend

__all__ = ["LLMBackend", "OllamaBackend"]
