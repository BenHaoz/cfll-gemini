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


def collect_skygb(cfg: dict[str, Any], *, today: date | None = None, year: int | None = None) -> tuple[list[Item], SourceStatus]:
    t0 = time.time()
    if not cfg.get("enabled", True):
        return [], SourceStatus(name=SOURCE, ok=True, message="disabled", kind="project")
    year = year or (today or date.today()).year
    base_params = {k: (str(v).replace("{year}", str(year)) if isinstance(v, str) else v)
                   for k, v in (cfg.get("params") or {}).items()}
    items: list[Item] = []
    pages = 0
    page_param = cfg.get("page_param", "p")
    disciplines = cfg.get("disciplines") or [base_params.get("xktype", "民族问题研究")]
    try:
        for disc in disciplines:
            prev_first = ""
            for p in range(1, int(cfg.get("max_pages", 3)) + 1):
                params = dict(base_params, xktype=disc, **{page_param: p})
                html = fetch_text(cfg["url"], params=params, snapshot=f"skygb_{disc}_p{p}")
                tables = parse_tables(soup_of(html))
                got = 0
                first_title = ""
                for rows in tables:
                    found = rows_to_projects(rows, source=SOURCE, funder="国家社科基金", url=cfg["url"],
                                             keywords=cfg.get("row_keywords"), default_date=str(year))
                    if found and not first_title:
                        first_title = found[0].title
                    got += len(found)
                    items.extend(found)
                pages += 1
                if got == 0 or (first_title and first_title == prev_first):   # 无数据或分页无效（重复页）
                    break
                prev_first = first_title
    except Exception as exc:  # noqa: BLE001
        if not items:
            return [], SourceStatus(name=SOURCE, ok=False, message=str(exc)[:300], elapsed=time.time() - t0, kind="project")
    uniq: dict[str, Item] = {}
    for it in items:
        uniq.setdefault(it.key(), it)
    out = list(uniq.values())
    for it in out:
        it.extra.setdefault("year", year)
    return out, SourceStatus(name=f"{SOURCE}·{year}", ok=True, count=len(out), message=f"检索 {pages} 页", elapsed=time.time() - t0, kind="project")
