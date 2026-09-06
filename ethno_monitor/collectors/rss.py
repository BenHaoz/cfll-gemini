"""RSS / Atom 订阅采集。"""
from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

from ..models import Item, SourceStatus
from .base import clean, parse_date, within_lookback


def collect_rss(feed: dict[str, Any], *, lookback_days: int, today: date | None = None,
                theme_keywords: dict[str, list[str]] | None = None) -> tuple[list[Item], SourceStatus]:
    """theme_keywords: {专题名: [英文/中文关键词]}；feed 可设 theme_filter: [专题名...] 只保留命中的条目。"""
    import feedparser  # noqa: WPS433

    t0 = time.time()
    name = feed.get("name", feed["url"])
    try:
        from ..http import fetch
        resp = fetch(feed["url"], timeout=30, retries=1, headers={"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
        parsed = feedparser.parse(resp.content)
    except Exception as exc:  # noqa: BLE001
        return [], SourceStatus(name=f"RSS·{name}", ok=False, message=str(exc)[:200], kind="notice")
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        return [], SourceStatus(name=f"RSS·{name}", ok=False, message=str(getattr(parsed, "bozo_exception", ""))[:200], kind="notice")
    items: list[Item] = []
    filters = feed.get("theme_filter") or []
    kw = theme_keywords or {}
    total = 0
    for e in parsed.entries:
        total += 1
        d = parse_date(e.get("published", "") or e.get("updated", "") or e.get("prism_coverdate", ""))
        for key in ("published_parsed", "updated_parsed"):
            if not d and e.get(key):
                tm = e[key]
                d = f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}"
        if not within_lookback(d, lookback_days, today):
            continue
        title = clean(e.get("title", ""))
        summary = clean(re.sub(r"<[^>]+>", " ", e.get("summary", "") or ""))[:400]
        authors = [clean(a.get("name", "")) for a in (e.get("authors") or []) if a.get("name")] or ([clean(e.get("author", ""))] if e.get("author") else [])
        text = f"{title} {summary}".lower()
        if filters and not any(any(k.lower() in text for k in kw.get(f, [])) for f in filters):
            continue
        items.append(Item(kind=feed.get("kind", "paper"), title=title, url=e.get("link", ""), source=name, date=d, authors=authors[:6],
                          extra={"summary": summary[:300], "lang": feed.get("lang", "en"), "source_theme": feed.get("source_theme", ""),
                                 "via": "rss", "publisher": feed.get("publisher", "")}))
    return items, SourceStatus(name=f"RSS·{name}", ok=True, count=len(items), message=f"条目 {total}，窗口内保留 {len(items)}",
                               elapsed=time.time() - t0, kind="journal")
