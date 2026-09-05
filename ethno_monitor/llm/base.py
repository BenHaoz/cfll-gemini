from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResearchResult:
    text: str
    urls: list[str] = field(default_factory=list)


class LLMClient:
    name = "llm"

    def generate(self, prompt: str, *, system: str = "", json_mode: bool = False, max_tokens: int = 8192) -> str:
        raise NotImplementedError

    def research(self, prompt: str, *, system: str = "", max_tokens: int = 8192) -> ResearchResult:
        """带联网检索的生成；默认退化为普通生成。"""
        return ResearchResult(text=self.generate(prompt, system=system, max_tokens=max_tokens))


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    """从模型输出中宽松地抽取 JSON（数组优先）。失败返回 None。"""
    if not text:
        return None
    cands = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for c in cands:
        c = c.strip()
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            pass
        for opener, closer in (("[", "]"), ("{", "}")):
            s, e = c.find(opener), c.rfind(closer)
            if s != -1 and e > s:
                try:
                    return json.loads(c[s:e + 1])
                except json.JSONDecodeError:
                    # 尝试去掉尾随逗号
                    try:
                        return json.loads(re.sub(r",\s*([\]}])", r"\1", c[s:e + 1]))
                    except json.JSONDecodeError:
                        continue
    return None
