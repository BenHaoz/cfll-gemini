"""期刊目录采集：期刊自建站 / CNKI 腾云采编系统目录页、国家哲学社会科学文献中心。"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any

from bs4 import Tag

from ..http import fetch, fetch_text
from ..models import Item, SourceStatus
from .base import CJK, clean, parse_date, soup_of, within_lookback

log = logging.getLogger(__name__)

ISSUE_RE = re.compile(r"(20\d{2})\s*年\s*第?\s*(\d{1,2})\s*期")
AUTHOR_SPLIT = re.compile(r"[、,，;；\s/]+")


def _issue_of(text: str) -> tuple[str, str]:
    m = ISSUE_RE.search(text)
    if not m:
        return "", ""
    return f"{m.group(1)}年第{int(m.group(2))}期", f"{m.group(1)}-{int(m.group(2)) * 2 - 1:02d}"


def parse_toc_generic(html: str, base_url: str, journal: str) -> list[Item]:
    """通用目录解析：找出含长中文标题链接的列表项/表格行，标题后紧随的短中文串视为作者。"""
    soup = soup_of(html)
    page_text = clean(soup.get_text(" "))
    issue, issue_date = _issue_of(page_text)
    items: list[Item] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        title = clean(a.get("title") or a.get_text(" "))
        href = a["href"]
        if len(title) < 6 or not CJK.search(title) or title in seen:
            continue
        low = href.lower()
        if not any(k in low for k in ("wktextcontent", "article", "abstract", "detail", "id=", "paper", "content", "info")):
            continue
        if re.search(r"(目录|下载|全文|摘要|返回|更多|首页|投稿|征稿|版权|订阅|点击|阅读)$", title):
            continue
        seen.add(title)
        container: Tag | None = a.find_parent(["li", "tr", "dd", "div", "p"])
        authors: list[str] = []
        if container is not None:
            ctx = clean(container.get_text(" "))
            rest = ctx.split(title, 1)[1] if title in ctx else ""
            rest = re.sub(r"\(\s*\d+\s*\)|\d+\s*[-–]\s*\d+|页码?|\d+", " ", rest)
            for tok in AUTHOR_SPLIT.split(rest):
                tok = tok.strip("()（）[]【】 ")
                if 2 <= len(tok) <= 4 and CJK.fullmatch(tok[0]) and tok not in ("摘要", "全文", "下载", "作者", "关键词"):
                    authors.append(tok)
                if len(authors) >= 6:
                    break
        from urllib.parse import urljoin
        items.append(Item(kind="paper", title=title, url=urljoin(base_url, href), source=journal,
                          date=issue_date, authors=authors[:6], extra={"issue": issue, "via": "toc"}))
    return items


def collect_journal_toc(journal: dict[str, Any], *, lookback_days: int, today: date | None = None) -> tuple[list[Item], SourceStatus]:
    name = journal["name"]
    t0 = time.time()
    pages = journal.get("toc_pages") or []
    if not pages:
        return [], SourceStatus(name=f"期刊站点·{name}", ok=True, count=0, message="未配置目录页（依赖文献中心/LLM 检索）", kind="journal")
    items: list[Item] = []
    errors: list[str] = []
    for pg in pages:
        try:
            html = fetch_text(pg["url"], snapshot=f"toc_{name}")
            items.extend(parse_toc_generic(html, pg["url"], name))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc)[:200])
    if not items and errors:
        return [], SourceStatus(name=f"期刊站点·{name}", ok=False, message="; ".join(errors)[:300], elapsed=time.time() - t0, kind="journal")
    return items, SourceStatus(name=f"期刊站点·{name}", ok=True, count=len(items), message=f"目录解析 {len(items)} 篇", elapsed=time.time() - t0, kind="journal")


# ---------------------------------------------------------------------------
# 国家哲学社会科学文献中心（ncpssd.cn）
# ---------------------------------------------------------------------------
_FIELD_ALIASES = {
    "title": ["title", "titlec", "name", "篇名", "题名"],
    "authors": ["authors", "author", "authorc", "作者", "creator"],
    "journal": ["journal", "journalname", "media", "mediac", "刊名", "source"],
    "date": ["pubdate", "publishdate", "publicationdate", "years", "year", "date", "showdate"],
    "issue": ["issue", "issuenum", "num", "期", "yearissue"],
    "id": ["id", "articleid", "guid", "lngid"],
}


def _pick(d: dict[str, Any], field: str) -> str:
    low = {str(k).lower(): v for k, v in d.items()}
    for alias in _FIELD_ALIASES[field]:
        if alias in low and low[alias] not in (None, ""):
            v = low[alias]
            if isinstance(v, list):
                return "、".join(str(x) for x in v)
            return str(v)
    return ""


def _find_records(obj: Any) -> list[dict[str, Any]]:
    """在任意 JSON 结构中找出"像文献记录"的字典列表。"""
    best: list[dict[str, Any]] = []
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, list) and cur and all(isinstance(x, dict) for x in cur):
            if any(_pick(x, "title") for x in cur[:3]) and len(cur) > len(best):
                best = cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return best


def collect_ncpssd(cfg: dict[str, Any], journals: list[dict[str, Any]], *, lookback_days: int,
                   today: date | None = None) -> tuple[list[Item], SourceStatus]:
    name = "国家哲学社会科学文献中心"
    t0 = time.time()
    if not cfg.get("enabled", True):
        return [], SourceStatus(name=name, ok=True, message="disabled", kind="journal")
    url = cfg.get("search_url", "https://www.ncpssd.cn/Literature/articlelist")
    size = int(cfg.get("page_size", 30))
    items: list[Item] = []
    fails = 0
    for j in journals:
        jname = j["name"]
        payloads = [
            {"searchKeyList": [{"key": jname, "type": "journalName", "match": "exact"}], "typeList": ["journalArticle"],
             "pageIndex": 1, "pageSize": size, "sortBy": "pubdate", "orderBy": "desc"},
            {"keyword": jname, "type": "journalArticle", "pageIndex": 1, "pageSize": size, "sort": "pubdate"},
        ]
        got = False
        for body in payloads:
            try:
                resp = fetch(url, method="POST", json=body, timeout=30, retries=1,
                             headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest",
                                      "Referer": "https://www.ncpssd.cn/"})
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                log.info("ncpssd %s payload failed: %s", jname, exc)
                continue
            recs = _find_records(data)
            if not recs:
                continue
            for r in recs:
                title = clean(_pick(r, "title"))
                if len(title) < 4:
                    continue
                d = parse_date(_pick(r, "date"))
                if not within_lookback(d, max(lookback_days, 45), today):
                    continue
                rid = _pick(r, "id")
                link = f"https://www.ncpssd.cn/Literature/articleinfo?type=journalArticle&typename=期刊论文&id={rid}" if rid else "https://www.ncpssd.cn/"
                items.append(Item(kind="paper", title=title, url=link, source=jname, date=d,
                                  authors=[a for a in AUTHOR_SPLIT.split(_pick(r, "authors")) if a][:6],
                                  extra={"issue": _pick(r, "issue"), "via": "ncpssd"}))
            got = True
            break
        if not got:
            fails += 1
    ok = fails < len(journals)
    msg = f"{len(journals) - fails}/{len(journals)} 刊检索成功，{len(items)} 篇"
    return items, SourceStatus(name=name, ok=ok, count=len(items), message=msg if ok else "接口不可用或结构变化（请核对 search_url / 请求体）",
                               elapsed=time.time() - t0, kind="journal")
