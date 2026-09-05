"""RSS / Atom 订阅采集。"""
from __future__ import annotations

import time
from datetime import date
from typing import Any

from ..models import Item, SourceStatus
from .base import clean, parse_date, within_lookback


def collect_rss(feed: dict[str, Any], *, lookback_days: int, today: date | None = None) -> tuple[list[Item], SourceStatus]:
    import feedparser  # noqa: WPS433

    t0 = time.time()
    name = feed.get("name", feed["url"])
    try:
        parsed = feedparser.parse(feed["url"])
    except Exception as exc:  # noqa: BLE001
        return [], SourceStatus(name=f"RSS·{name}", ok=False, message=str(exc)[:200], kind="notice")
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        return [], SourceStatus(name=f"RSS·{name}", ok=False, message=str(getattr(parsed, "bozo_exception", ""))[:200], kind="notice")
    items: list[Item] = []
    for e in parsed.entries:
        d = parse_date(e.get("published", "") or e.get("updated", ""))
        if not d and e.get("published_parsed"):
            tm = e["published_parsed"]
            d = f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}"
        if not within_lookback(d, lookback_days, today):
            continue
        items.append(Item(kind=feed.get("kind", "notice"), title=clean(e.get("title", "")), url=e.get("link", ""),
                          source=name, date=d, extra={"summary": clean(e.get("summary", ""))[:300]}))
    return items, SourceStatus(name=f"RSS·{name}", ok=True, count=len(items), elapsed=time.time() - t0, kind="notice")
