"""Gemini generateContent 客户端（支持 google_search grounding，可经自建反代访问）。"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from ..config import LLMSettings
from .base import LLMClient, ResearchResult

log = logging.getLogger(__name__)


class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self, s: LLMSettings):
        self.key = s.gemini_api_key
        self.base = s.gemini_base_url
        self.model = s.gemini_model
        self.timeout = s.timeout

    def _call(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base}/v1beta/models/{self.model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.key}
        last: Exception | None = None
        for attempt in range(4):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=self.timeout)
                if r.status_code in (429, 500, 503) and attempt < 3:
                    time.sleep(4 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                last = exc
                log.warning("gemini call failed (%d): %s", attempt + 1, exc)
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"Gemini 调用失败: {last}")

    @staticmethod
    def _text(data: dict[str, Any]) -> str:
        parts = []
        for c in data.get("candidates", [])[:1]:
            for p in c.get("content", {}).get("parts", []):
                if "text" in p:
                    parts.append(p["text"])
        return "".join(parts)

    def generate(self, prompt: str, *, system: str = "", json_mode: bool = False, max_tokens: int = 8192) -> str:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        return self._text(self._call(body))

    def research(self, prompt: str, *, system: str = "", max_tokens: int = 8192) -> ResearchResult:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._call(body)
        urls: list[str] = []
        for c in data.get("candidates", [])[:1]:
            gm = c.get("groundingMetadata") or {}
            for ch in gm.get("groundingChunks", []):
                uri = (ch.get("web") or {}).get("uri")
                if uri and uri not in urls:
                    urls.append(uri)
        return ResearchResult(text=self._text(data), urls=urls)
