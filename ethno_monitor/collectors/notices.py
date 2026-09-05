"""通知公告类来源（社科办 / 国家民委 / 教育部 / sinoss）：列表页 -> 关键词过滤 -> 立项名单下钻。"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from ..http import fetch, fetch_text
from ..models import Item, SourceStatus
from .base import (date_from_url, extract_links, find_attachments, has_any, parse_date, parse_tables,
                   parse_xlsx, rows_to_projects, soup_of, within_lookback)

log = logging.getLogger(__name__)


def collect_notice_source(src: dict[str, Any], *, lookback_days: int, drill_cfg: dict[str, Any],
                          today: date | None = None) -> tuple[list[Item], SourceStatus]:
    name = src["name"]
    funder = src.get("funder", name)
    t0 = time.time()
    items: list[Item] = []
    errors: list[str] = []
    seen_urls: set[str] = set()
    for url in src.get("urls", []):
        try:
            html = fetch_text(url, snapshot=f"notice_{name}_{len(seen_urls)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            continue
        soup = soup_of(html)
        for link in extract_links(soup, url, src.get("link_regex", "")):
            if link["url"] in seen_urls:
                continue
            seen_urls.add(link["url"])
            title = link["title"]
            if src.get("include_keywords") and not has_any(title, src["include_keywords"]):
                continue
            if src.get("exclude_keywords") and has_any(title, src["exclude_keywords"]):
                continue
            d = date_from_url(link["url"], src.get("url_date_regex", "")) or parse_date(link["context"])
            if not within_lookback(d, lookback_days, today):
                continue
            items.append(Item(kind="notice", title=title, url=link["url"], source=name, date=d,
                              extra={"funder": funder}))
    if not seen_urls and errors:
        return [], SourceStatus(name=name, ok=False, message="; ".join(errors)[:300], elapsed=time.time() - t0, kind="notice")

    # 下钻：立项名单 -> 课题条目
    projects: list[Item] = []
    if drill_cfg.get("enabled", True):
        budget = int(drill_cfg.get("max_pages", 10))
        drill_kw = src.get("drilldown_keywords", ["立项", "名单"])
        for n in items:
            if budget <= 0:
                break
            if not has_any(n.title, drill_kw):
                continue
            budget -= 1
            try:
                projects.extend(drill_notice(n, drill_cfg))
            except Exception as exc:  # noqa: BLE001
                log.warning("drilldown %s failed: %s", n.url, exc)
                n.extra["drilldown_error"] = str(exc)[:200]
    msg = f"通知 {len(items)} 条，下钻得课题 {len(projects)} 条"
    if errors:
        msg += f"；部分列表页失败: {len(errors)}"
    return items + projects, SourceStatus(name=name, ok=True, count=len(items) + len(projects), message=msg,
                                          elapsed=time.time() - t0, kind="project")


def drill_notice(notice: Item, drill_cfg: dict[str, Any]) -> list[Item]:
    """抓取公告正文，解析表格与 xlsx 附件，抽取民族学相关课题。"""
    html = fetch_text(notice.url, snapshot=f"drill_{notice.key()}")
    soup = soup_of(html)
    funder = notice.extra.get("funder", notice.source)
    row_kw = drill_cfg.get("row_keywords", ["民族"])
    # 公告标题本身已限定为民族类（如"铸牢…专项立项名单"）时，不再逐行过滤
    whole_relevant = has_any(notice.title, ["民族", "铸牢", "共同体"])
    kws = None if whole_relevant else row_kw
    ptype_hint = _guess_type(notice.title)
    out: list[Item] = []
    for rows in parse_tables(soup):
        out.extend(rows_to_projects(rows, source=notice.source, funder=funder, url=notice.url,
                                    keywords=kws, default_date=notice.date, ptype_hint=ptype_hint))
    atts = find_attachments(soup, notice.url)
    notice.extra["attachments"] = [a["url"] for a in atts][:10]
    for att in atts[:4]:
        if att["url"].lower().split("?")[0].endswith(".xlsx"):
            try:
                resp = fetch(att["url"], timeout=40)
                for rows in parse_xlsx(resp.content):
                    out.extend(rows_to_projects(rows, source=notice.source, funder=funder, url=att["url"],
                                                keywords=kws, default_date=notice.date, ptype_hint=ptype_hint))
            except Exception as exc:  # noqa: BLE001
                log.warning("attachment %s failed: %s", att["url"], exc)
    # 去重
    uniq: dict[str, Item] = {}
    for it in out:
        it.extra["from_notice"] = notice.title
        uniq.setdefault(it.key(), it)
    notice.extra["projects_found"] = len(uniq)
    return list(uniq.values())


def _guess_type(title: str) -> str:
    for k in ["重大项目", "重点项目", "青年项目", "一般项目", "西部项目", "后期资助", "冷门绝学", "专项", "重大课题攻关", "年度项目"]:
        if k in title:
            return k
    return ""
