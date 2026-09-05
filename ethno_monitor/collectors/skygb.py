"""国家社科基金项目数据库（fz.people.com.cn/skygb/sk）：按学科"民族学"检索当年立项。"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from ..http import fetch_text
from ..models import Item, SourceStatus
from .base import parse_tables, rows_to_projects, soup_of

log = logging.getLogger(__name__)

SOURCE = "国家社科基金项目数据库"


def collect_skygb(cfg: dict[str, Any], *, today: date | None = None) -> tuple[list[Item], SourceStatus]:
    t0 = time.time()
    if not cfg.get("enabled", True):
        return [], SourceStatus(name=SOURCE, ok=True, message="disabled", kind="project")
    year = (today or date.today()).year
    base_params = {k: (str(v).replace("{year}", str(year)) if isinstance(v, str) else v)
                   for k, v in (cfg.get("params") or {}).items()}
    items: list[Item] = []
    pages = 0
    try:
        for p in range(1, int(cfg.get("max_pages", 3)) + 1):
            params = dict(base_params, p=p)
            html = fetch_text(cfg["url"], params=params, snapshot=f"skygb_p{p}")
            tables = parse_tables(soup_of(html))
            if not tables or len(html) < 200:
                html = fetch_text(cfg["url"], method="POST", data=params, snapshot=f"skygb_post_p{p}")
                tables = parse_tables(soup_of(html))
            got = 0
            for rows in tables:
                found = rows_to_projects(rows, source=SOURCE, funder="国家社科基金", url=cfg["url"],
                                         keywords=cfg.get("row_keywords"), default_date=str(year))
                got += len(found)
                items.extend(found)
            pages += 1
            if got == 0:
                break
    except Exception as exc:  # noqa: BLE001
        if not items:
            return [], SourceStatus(name=SOURCE, ok=False, message=str(exc)[:300], elapsed=time.time() - t0, kind="project")
    uniq: dict[str, Item] = {}
    for it in items:
        uniq.setdefault(it.key(), it)
    out = list(uniq.values())
    return out, SourceStatus(name=SOURCE, ok=True, count=len(out), message=f"检索 {pages} 页", elapsed=time.time() - t0, kind="project")
