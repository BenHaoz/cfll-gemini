"""四方向关键词分类器 + 广西相关性标注。"""
from __future__ import annotations

from typing import Any, Iterable

from .config import DIRECTIONS
from .models import Item


class Classifier:
    def __init__(self, keywords_cfg: dict[str, Any]):
        self.cfg = keywords_cfg
        self.default = keywords_cfg.get("default_direction", "中华民族学")
        self.priority: list[str] = keywords_cfg.get("priority", DIRECTIONS)
        self.rules: dict[str, list[tuple[str, int]]] = {}
        for name, spec in (keywords_cfg.get("directions") or {}).items():
            self.rules[name] = [(kw["k"], int(kw.get("w", 1))) for kw in spec.get("keywords", [])]
        self.ethno_kw: list[str] = keywords_cfg.get("ethnology_keywords", ["民族"])
        self.gx_kw: list[str] = keywords_cfg.get("guangxi_keywords", ["广西"])

    def score(self, text: str) -> dict[str, int]:
        scores: dict[str, int] = {}
        for name, rules in self.rules.items():
            s = 0
            for kw, w in rules:
                if kw and kw in text:
                    s += w
            scores[name] = s
        return scores

    def classify_text(self, text: str) -> str:
        scores = self.score(text)
        best = max(scores.values()) if scores else 0
        if best <= 0:
            return self.default
        for name in self.priority:
            if scores.get(name, 0) == best:
                return name
        return max(scores, key=scores.get)  # pragma: no cover

    def is_ethnology(self, text: str) -> bool:
        return any(k in text for k in self.ethno_kw)

    def is_guangxi(self, text: str) -> bool:
        return any(k in text for k in self.gx_kw)

    def annotate(self, item: Item) -> Item:
        text = " ".join([item.title, item.source, item.affiliation, " ".join(item.authors),
                         str(item.extra.get("summary", "")), str(item.extra.get("keywords", ""))])
        if not item.direction or item.direction not in self.rules:
            item.direction = self.classify_text(text)
        item.guangxi_related = self.is_guangxi(text)
        return item

    def annotate_all(self, items: Iterable[Item]) -> list[Item]:
        return [self.annotate(i) for i in items]
