"""数据模型。"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any

_PUNCT = re.compile(r"[\s　·•・,，.。;；:：!！?？\"“”'‘’()（）\[\]【】《》<>〈〉—\-–_/\\|]+")


def normalize_title(title: str) -> str:
    t = title or ""
    t = t.replace("（", "(").replace("）", ")")
    t = _PUNCT.sub("", t)
    return t.lower()


@dataclass
class Item:
    kind: str                       # paper | project | notice
    title: str
    url: str = ""
    source: str = ""                # 期刊名 / 资助机构 / 网站
    date: str = ""                  # YYYY-MM-DD 或 YYYY-MM 或 YYYY
    authors: list[str] = field(default_factory=list)
    affiliation: str = ""
    direction: str = ""
    guangxi_related: bool = False
    verified: bool = True           # False = 仅 LLM 检索得到且无来源链接支撑
    evidence: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)  # issue / funder / project_type / pi / summary ...

    def key(self) -> str:
        base = f"{self.kind}|{normalize_title(self.title)}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Item":
        allowed = {f for f in Item.__dataclass_fields__}
        return Item(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class SourceStatus:
    name: str
    ok: bool
    count: int = 0
    message: str = ""
    elapsed: float = 0.0
    kind: str = ""                  # journal | project | notice | llm

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
