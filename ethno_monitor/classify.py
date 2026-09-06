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
        self.themes: dict[str, Any] = keywords_cfg.get("themes") or {}

    def theme_tags(self, text: str, *, lang: str = "zh", source_theme: str = "") -> list[str]:
        """专题标签：中文按 keywords_cn，英文按 keywords_en（可要求同时含民族语境词）。source_theme 为数据源预设专题。"""
        tags: list[str] = []
        low = text.lower()
        for name, spec in self.themes.items():
            hit = False
            if lang == "zh":
                hit = any(k in text for k in spec.get("keywords_cn", []))
            else:
                hit = any(k.lower() in low for k in spec.get("keywords_en", []))
                if hit and spec.get("require_ethnic_context_en"):
                    hit = any(k.lower() in low for k in spec.get("ethnic_context_en", []))
            if hit or source_theme == name:
                tags.append(name)
        return tags

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
        # 涉桂判定不看期刊名（否则广西刊物的全部文章都会被标记），只看题目/单位/摘要
        gx_text = " ".join([item.title, item.affiliation, str(item.extra.get("summary", "")), str(item.extra.get("keywords", ""))])
        item.guangxi_related = self.is_guangxi(gx_text)
        lang = str(item.extra.get("lang", "zh"))
        item.extra["themes"] = self.theme_tags(f"{item.title} {item.extra.get('summary', '')}", lang=lang, source_theme=str(item.extra.get("source_theme", "")))
        return item

    def annotate_all(self, items: Iterable[Item]) -> list[Item]:
        return [self.annotate(i) for i in items]
