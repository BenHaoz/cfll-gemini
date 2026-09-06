"""国家社科基金项目数据库（fz.people.com.cn/skygb/sk）：按学科"民族学"检索当年立项。"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from urllib.parse import urljoin

from ..http import fetch_text
from ..models import Item, SourceStatus
from .base import clean, parse_tables, rows_to_projects, soup_of

log = logging.getLogger(__name__)

SOURCE = "国家社科基金项目数据库"


def next_page_href(soup, page_url: str) -> str:
    """从翻页区取“下一页”链接（站点为 ThinkPHP 路径式翻页，锚点可能为 //host/... 协议相对地址）。"""
    for a in soup.find_all("a", href=True):
        if clean(a.get_text()) in ("下一页", ">", "»"):
            href = a["href"].strip()
            if href.startswith("//"):
                href = "http:" + href
            return urljoin(page_url, href)
    return ""


def _fetch_next_page(cfg: dict[str, Any], disc: str, p: int, params: dict[str, Any], next_href: str, prev_first: str) -> str | None:
    """第 p 页：优先跟随“下一页”锚点；否则构造路径式 /index/seach/{p}?xktype=…&lxtime=…；均无新内容则返回 None。"""
    candidates: list[tuple[str, dict[str, Any] | None]] = []
    if next_href:
        candidates.append((next_href, None))
    base = cfg["url"].rstrip("/")
    slim = {k: v for k, v in params.items() if k in ("xktype", "lxtime")}
    candidates.append((f"{base}/{p}", slim))
    low = base.replace("/Index/seach", "/index/seach")
    if low != base:
        candidates.append((f"{low}/{p}", slim))
    candidates.append((base, dict(params, **{cfg.get("page_param", "p"): p})))
    for url, prm in candidates:
        try:
            html = fetch_text(url, params=prm, snapshot=f"skygb_{disc}_p{p}", retries=0)
        except Exception as exc:  # noqa: BLE001
            log.warning("skygb page %s via %s failed: %s", p, url, exc)
            continue
        soup = soup_of(html)
        first = ""
        for rows in parse_tables(soup):
            found = rows_to_projects(rows, source=SOURCE, funder="国家社科基金", url=cfg["url"], keywords=None)
            if found:
                first = found[0].title
                break
        if first and first != prev_first:
            return html
    return None


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
            next_href = ""
            for p in range(1, int(cfg.get("max_pages", 3)) + 1):
                params = dict(base_params, xktype=disc)
                if p == 1:
                    html = fetch_text(cfg["url"], params=params, snapshot=f"skygb_{disc}_p{p}")
                else:
                    html = _fetch_next_page(cfg, disc, p, params, next_href, prev_first)
                    if html is None:
                        break
                soup = soup_of(html)
                tables = parse_tables(soup)
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
                next_href = next_page_href(soup, cfg["url"])
                if not next_href and cfg.get("page_mode", "path") != "path":
                    break
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
