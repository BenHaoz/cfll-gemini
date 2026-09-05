"""Anthropic Messages API 客户端（可选，支持 web_search 工具）。"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from ..config import LLMSettings
from .base import LLMClient, ResearchResult

log = logging.getLogger(__name__)


class AnthropicClient(LLMClient):
    name = "anthropic"

    def __init__(self, s: LLMSettings):
        self.key = s.anthropic_api_key
        self.base = s.anthropic_base_url
        self.model = s.anthropic_model
        self.timeout = s.timeout

    def _call(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"content-type": "application/json", "x-api-key": self.key, "anthropic-version": "2023-06-01"}
        last: Exception | None = None
        for attempt in range(4):
            try:
                r = requests.post(f"{self.base}/v1/messages", json=body, headers=headers, timeout=self.timeout)
                if r.status_code in (429, 500, 529) and attempt < 3:
                    time.sleep(4 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                last = exc
                log.warning("anthropic call failed (%d): %s", attempt + 1, exc)
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"Anthropic 调用失败: {last}")

    def generate(self, prompt: str, *, system: str = "", json_mode: bool = False, max_tokens: int = 8192) -> str:
        body: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system + ("\n只输出 JSON，不要任何解释。" if json_mode else "")
        data = self._call(body)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    def research(self, prompt: str, *, system: str = "", max_tokens: int = 8192) -> ResearchResult:
        body: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                "messages": [{"role": "user", "content": prompt}],
                                "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]}
        if system:
            body["system"] = system
        data = self._call(body)
        text, urls = [], []
        for b in data.get("content", []):
            if b.get("type") == "text":
                text.append(b.get("text", ""))
                for cit in b.get("citations", []) or []:
                    u = cit.get("url")
                    if u and u not in urls:
                        urls.append(u)
            elif b.get("type") == "web_search_tool_result":
                for r in b.get("content", []) or []:
                    u = r.get("url") if isinstance(r, dict) else None
                    if u and u not in urls:
                        urls.append(u)
        return ResearchResult(text="".join(text), urls=urls)
