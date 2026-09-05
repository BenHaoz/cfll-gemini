"""LLM 客户端（Gemini / Anthropic）。"""
from __future__ import annotations

from ..config import LLMSettings
from .base import LLMClient, ResearchResult, extract_json


def make_client(settings: LLMSettings) -> LLMClient | None:
    if settings.provider == "gemini" and settings.gemini_api_key:
        from .gemini import GeminiClient
        return GeminiClient(settings)
    if settings.provider == "anthropic" and settings.anthropic_api_key:
        from .anthropic import AnthropicClient
        return AnthropicClient(settings)
    return None


__all__ = ["LLMClient", "ResearchResult", "extract_json", "make_client"]
