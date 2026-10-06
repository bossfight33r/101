"""LLM-бэкенды: Anthropic (production) и Fake (тесты)."""

from techstudio.core.llm.base import LLMClient, LLMError, extract_json

__all__ = ["LLMClient", "LLMError", "extract_json"]
