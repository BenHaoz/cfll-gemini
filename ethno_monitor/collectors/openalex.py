"""国外文献：OpenAlex（主）/ Crossref（备）开放 API，按期刊 ISSN 或主题检索式取最近文献。
无需密钥、无反爬；在 GitHub 运行器上可直连。返回题名、作者及机构、摘要（OpenAlex 倒排索引还原）、DOI。"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

from ..http import fetch
from ..models import Item, SourceStatus
from .base import clean

log = logging.getLogger(__name__)
OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"
MAILTO = "ethno-monitor@example.org"


def _abstract(inv: dict[str, list[int]] | None) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for w, idxs in inv.items():
        for i in idxs:
            pos[i] = w
    return " ".join(pos[i] for i in sorted(pos))[:1500]


def _openalex_items(params: dict[str, Any], *, source_name: str, source_theme: str, per_page: int = 50,
                    sort: str = "publication_date:desc") -> list[Item]:
    params = dict(params, **{"per-page": per_page, "mailto": MAILTO, "sort": sort})
    data = fetch(OPENALEX, params=params, timeout=40, retries=1, headers={"Accept": "application/json"}).json()
    items: list[Item] = []
    for w in data.get("results", []):
        title = clean(w.get("title") or w.get("display_name") or "")
        if len(title) < 6:
            continue
        auths, insts = [], []
        for a in w.get("authorships", [])[:8]:
            n = (a.get("author") or {}).get("display_name")
            if n:
                auths.append(n)
            for ins in a.get("institutions", []) or []:
                if ins.get("display_name") and ins["display_name"] not in insts:
                    insts.append(ins["display_name"])
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or source_name
        topics = [t.get("display_name", "") for t in (w.get("topics") or [])[:3]]
        items.append(Item(kind="paper", title=title, url=w.get("doi") or (w.get("primary_location") or {}).get("landing_page_url") or w.get("id", ""),
                          source=src, date=(w.get("publication_date") or "")[:10], authors=auths[:6], affiliation="; ".join(insts[:4]),
                          extra={"summary": _abstract(w.get("abstract_inverted_index")), "lang": "en", "source_theme": source_theme,
                                 "via": "openalex", "topics": topics, "journal_query": source_name}))
    return items


def _crossref_items(issn: str, since: str, *, source_name: str, source_theme: str) -> list[Item]:
    params = {"filter": f"issn:{issn},from-pub-date:{since}", "sort": "published", "order": "desc", "rows": 50, "mailto": MAILTO}
    data = fetch(CROSSREF, params=params, timeout=40, retries=1, headers={"Accept": "application/json"}).json()
    items: list[Item] = []
    for w in (data.get("message") or {}).get("items", []):
        title = clean(" ".join(w.get("title") or []))
        if len(title) < 6:
            continue
        auths = [clean(f"{a.get('given', '')} {a.get('family', '')}") for a in w.get("author", [])[:6]]
        insts = []
        for a in w.get("author", [])[:8]:
            for af in a.get("affiliation", []) or []:
                if af.get("name") and af["name"] not in insts:
                    insts.append(af["name"])
        parts = ((w.get("published") or w.get("issued") or {}).get("date-parts") or [[None]])[0]
        d = "-".join(f"{int(x):02d}" if i else str(x) for i, x in enumerate(parts) if x) if parts and parts[0] else ""
        items.append(Item(kind="paper", title=title, url=w.get("URL") or "", source=clean(" ".join(w.get("container-title") or [])) or source_name,
                          date=d, authors=[a for a in auths if a], affiliation="; ".join(insts[:4]),
                          extra={"summary": clean(w.get("abstract", ""))[:1500], "lang": "en", "source_theme": source_theme, "via": "crossref"}))
    return items


def collect_foreign_journal(j: dict[str, Any], *, lookback_days: int, today: date | None = None,
                            theme_keywords: dict[str, list[str]] | None = None,
                            theme_tagger: Any = None) -> tuple[list[Item], SourceStatus]:
    """j: {name, issn: [..], source_theme, theme_filter: [...]}。theme_tagger(text) -> [专题名]（优先，含民族语境判定）。"""
    today = today or date.today()
    since = (today - timedelta(days=lookback_days)).isoformat()
    t0 = time.time()
    issns = [x for x in (j.get("issn") or []) if x]
    items: list[Item] = []
    via = ""
    try:
        params = {"filter": f"primary_location.source.issn:{'|'.join(issns)},from_publication_date:{since},type:article"}
        items = _openalex_items(params, source_name=j["name"], source_theme=j.get("source_theme", ""))
        via = "openalex"
    except Exception as exc:  # noqa: BLE001
        log.warning("openalex %s failed: %s", j["name"], exc)
        try:
            for issn in issns[:2]:
                items += _crossref_items(issn, since, source_name=j["name"], source_theme=j.get("source_theme", ""))
            via = "crossref"
        except Exception as exc2:  # noqa: BLE001
            return [], SourceStatus(name=f"国外期刊·{j['name']}", ok=False, message=f"openalex/crossref 均失败: {str(exc2)[:120]}", elapsed=time.time() - t0, kind="journal")
    filters = j.get("theme_filter") or []
    if filters and (theme_tagger or theme_keywords):
        kept = []
        for it in items:
            text = f"{it.title} {it.extra.get('summary', '')}"
            if theme_tagger is not None:
                hit = bool(set(theme_tagger(text)) & set(filters))
            else:
                hit = any(any(k.lower() in text.lower() for k in (theme_keywords or {}).get(f, [])) for f in filters)
            if hit:
                kept.append(it)
        msg = f"{via}: 近 {lookback_days} 天 {len(items)} 篇，命中专题 {len(kept)} 篇"
        items = kept
    else:
        msg = f"{via}: 近 {lookback_days} 天 {len(items)} 篇"
    return items, SourceStatus(name=f"国外期刊·{j['name']}", ok=True, count=len(items), message=msg, elapsed=time.time() - t0, kind="journal")


def collect_foreign_topic(q: dict[str, Any], *, lookback_days: int, today: date | None = None,
                         theme_tagger: Any = None) -> tuple[list[Item], SourceStatus]:
    """OpenAlex 主题检索式：q = {name, search, source_theme}（跨期刊，抓国外少数民族/土著现代化研究等）。
    只保留期刊文章；若给定 theme_tagger，则要求题名/摘要本身命中该专题词（source_theme 只作提示，不再无条件打标签）。"""
    today = today or date.today()
    since = (today - timedelta(days=lookback_days)).isoformat()
    t0 = time.time()
    try:
        # 只检索题名+摘要，限定社会科学域（domain 2），排除超前日期的预印/占位记录
        until = (today + timedelta(days=7)).isoformat()
        params = {"filter": f"title_and_abstract.search:{q['search']},from_publication_date:{since},to_publication_date:{until},"
                            f"type:article,language:en,primary_topic.domain.id:{q.get('domain', 2)},primary_location.source.type:journal"}
        items = _openalex_items(params, source_name=q["name"], source_theme=q.get("source_theme", ""), per_page=int(q.get("max", 30)),
                                sort=q.get("sort", "relevance_score:desc"))
    except Exception as exc:  # noqa: BLE001
        return [], SourceStatus(name=f"国外主题检索·{q['name']}", ok=False, message=str(exc)[:150], elapsed=time.time() - t0, kind="journal")
    fetched = len(items)
    theme = q.get("source_theme", "")
    if theme_tagger is not None and theme:
        items = [it for it in items if theme in theme_tagger(f"{it.title} {it.extra.get('summary', '')}")]
    msg = f"openalex 近 {lookback_days} 天 {fetched} 篇" + (f"，命中专题 {len(items)} 篇" if fetched != len(items) or theme_tagger else "")
    return items, SourceStatus(name=f"国外主题检索·{q['name']}", ok=True, count=len(items), message=msg, elapsed=time.time() - t0, kind="journal")
