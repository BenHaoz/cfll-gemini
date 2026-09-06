"""三年发文抓取：按核心期刊 × 年份 × 期号抓取文献中心期刊页，补抓详情页作者单位，写入 data/pubs/articles.jsonl。
预算式增量：每次运行最多抓取 max_issue_pages 个期页、max_detail_pages 个详情页；已完成的期不再重抓（记录于 data/pubs/harvest_state.json）。"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .collectors.base import clean, soup_of
from .collectors.journals import parse_toc_ncpssd
from .config import CONFIG_DIR
from .http import fetch, fix_encoding
from .pubs import ARTICLES_PATH, PUBS_DIR, Article, InstitutionMatcher, article_key, load_articles, save_articles, upsert

log = logging.getLogger(__name__)
STATE_PATH = PUBS_DIR / "harvest_state.json"
ISSUES_PER_YEAR = {"月刊": 12, "双月刊": 6, "季刊": 4, "半月刊": 24}

AFF_PATTERNS = [
    re.compile(r"作者单位[:：]?\s*(.{2,300}?)(?:关键词|摘要|分类号|来源|$)"),
    re.compile(r"机构[:：]?\s*(.{2,300}?)(?:关键词|摘要|分类号|来源|$)"),
]
BRACKET_AFF = re.compile(r"\[(\d+)\]\s*([^\[\];；]{2,80}?)(?=\s*\[\d+\]|\s*$|；|;)")


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"done_issues": {}, "runs": []}


def save_state(st: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def issue_url(gch: str, year: int, num: int) -> str:
    return f"https://m.ncpssd.cn/journal/details?gch={gch}&years={year}&num={num}&nav=1&langType=1"


META_API = "https://www.ncpssd.cn/articleinfoHandler/getjournalarticletable"


def fetch_article_meta(art_id: str) -> dict[str, Any]:
    """文献中心文章元数据接口（详情页 articleinfo.js 所用）：返回 data 字典，含 showwriter / showorgan / titlec / mediac 等。"""
    from urllib.parse import quote
    body = {"lngid": art_id, "type": "中文期刊文章", "pageType": 1}
    referer = f"https://www.ncpssd.cn/Literature/articleinfo?id={art_id}&type=journalArticle&typename={quote('中文期刊文章')}&nav=1&langType=1"
    resp = fetch(META_API, method="POST", json=body, timeout=25, retries=1,
                 headers={"Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest", "Referer": referer})
    data = resp.json()
    d = data.get("data") if isinstance(data, dict) else None
    return d if isinstance(d, dict) else {}


def split_organ(showorgan: str) -> list[str]:
    parts = [re.sub(r"^\[\d+\]\s*", "", x).strip() for x in re.split(r"[;；]", showorgan or "") if x.strip()]
    return [p for p in parts if p and p != "不详"][:10]


def parse_detail_affiliations(html: str) -> list[str]:
    """从文献详情页抽取作者单位：优先结构化标签，其次 [n] 单位 形式。"""
    soup = soup_of(html)
    for t in soup.find_all(["script", "style", "header", "nav", "footer"]):
        t.decompose()
    # 结构化：任何含"作者单位/机构"字样的标签，取其后继文本
    for lab in soup.find_all(string=re.compile(r"作者单位|机构")):
        parent = lab.parent
        cand = clean(parent.get_text(" "))
        if len(cand) < 6 and parent.parent is not None:
            cand = clean(parent.parent.get_text(" "))
        cand = re.sub(r"^.*?(作者单位|机构)[:：]?", "", cand)
        parts = [p.strip() for p in re.split(r"[;；]|(?=\[\d+\])", cand) if p.strip()]
        parts = [re.sub(r"^\[\d+\]\s*", "", p) for p in parts]
        parts = [p for p in parts if 2 <= len(p) <= 80 and not re.search(r"关键词|摘要|分类号", p)]
        if parts:
            return parts[:8]
    text = clean(soup.get_text(" "))
    for pat in AFF_PATTERNS:
        m = pat.search(text)
        if m:
            parts = [re.sub(r"^\[\d+\]\s*", "", p).strip() for p in re.split(r"[;；]|(?=\[\d+\])", m.group(1)) if p.strip()]
            parts = [p for p in parts if 2 <= len(p) <= 80]
            if parts:
                return parts[:8]
    found = BRACKET_AFF.findall(text)
    if found:
        return [f for _, f in found if re.search(r"大学|学院|研究|中心|所|党校|科学院|馆|会", f)][:8]
    return []


PROJECTS_PATH = PUBS_DIR / "projects.jsonl"


def harvest_projects(*, today: date | None = None, years_back: int = 3) -> dict[str, Any]:
    """国家社科基金项目数据库：学科“民族问题研究”近三年立项，匹配单位后写入 data/pubs/projects.jsonl。"""
    from .collectors.skygb import collect_skygb
    today = today or date.today()
    src = yaml.safe_load(open(CONFIG_DIR / "sources.yaml", encoding="utf-8")) or {}
    insts = yaml.safe_load(open(CONFIG_DIR / "institutions.yaml", encoding="utf-8")) or {}
    matcher = InstitutionMatcher(insts.get("institutions", []))
    cfg = dict(src.get("skygb", {}))
    cfg["max_pages"] = int(cfg.get("max_pages_harvest", 40))
    cfg["row_keywords"] = None
    existing: dict[str, dict[str, Any]] = {}
    if PROJECTS_PATH.exists():
        for line in open(PROJECTS_PATH, encoding="utf-8"):
            if line.strip():
                d = json.loads(line)
                existing[d["key"]] = d
    stat: dict[str, Any] = {}
    for y in range(today.year - years_back + 1, today.year + 1):
        items, status = collect_skygb(cfg, today=today, year=y)
        stat[str(y)] = {"ok": status.ok, "count": len(items), "message": status.message}
        for it in items:
            key = f"{y}|{it.title}"
            unit = it.affiliation
            existing[key] = {"key": key, "title": it.title, "pi": it.extra.get("pi", ""), "unit": unit,
                             "institutions": matcher.match_all([unit]), "funder": "国家社科基金", "type": it.extra.get("project_type", ""),
                             "discipline": it.extra.get("discipline", ""), "year": y, "no": it.extra.get("project_no", ""), "url": it.url}
        time.sleep(1.0)
    PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROJECTS_PATH, "w", encoding="utf-8") as f:
        for d in sorted(existing.values(), key=lambda x: (x["year"], x["title"])):
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return {"projects": len(existing), "by_year": stat}


def harvest(*, today: date | None = None, years_back: int = 3, max_issue_pages: int = 60, max_detail_pages: int = 300,
            sleep_s: float = 0.6, journals_filter: str | None = None) -> dict[str, Any]:
    today = today or date.today()
    core = yaml.safe_load(open(CONFIG_DIR / "journals_core.yaml", encoding="utf-8")) or {}
    insts = yaml.safe_load(open(CONFIG_DIR / "institutions.yaml", encoding="utf-8")) or {}
    matcher = InstitutionMatcher(insts.get("institutions", []))
    arts = load_articles()
    st = load_state()
    done: dict[str, Any] = st.setdefault("done_issues", {})
    years = list(range(today.year - years_back + 1, today.year + 1))
    issue_budget, detail_budget = max_issue_pages, max_detail_pages
    log_rows: list[str] = []

    journals = [j for j in core.get("journals", []) if j.get("gch") and j.get("tier") in ("CSSCI来源", "CSSCI扩展", "北大核心")]
    if journals_filter:
        journals = [j for j in journals if journals_filter in j["name"]]

    # 1) 期页：按刊×年×期，优先未完成的近期
    for j in journals:
        n_per_year = ISSUES_PER_YEAR.get(j.get("frequency", "双月刊"), 6)
        for y in years:
            for num in range(1, n_per_year + 1):
                key = f"{j['gch']}|{y}|{num}"
                if key in done or issue_budget <= 0:
                    continue
                # 当年未来期次跳过（按刊期估算月份）
                est_month = {12: num, 6: 2 * num - 1, 4: 3 * num - 2, 24: (num + 1) // 2}.get(n_per_year, 2 * num - 1)
                if y == today.year and est_month > today.month:
                    continue
                url = issue_url(j["gch"], y, num)
                try:
                    html = fix_encoding(fetch(url, timeout=25, retries=1))
                    items = parse_toc_ncpssd(html, url, j["name"])
                except Exception as exc:  # noqa: BLE001
                    log.warning("issue %s failed: %s", url, exc)
                    issue_budget -= 1
                    continue
                issue_budget -= 1
                # 页面实际期号须与请求一致（避免回落到当期）
                got_issue = items[0].extra.get("issue", "") if items else ""
                if items and got_issue and got_issue != f"{y}年第{num}期":
                    done[key] = {"status": "not_found", "got": got_issue}
                    continue
                new_arts = []
                for it in items:
                    new_arts.append(Article(key=article_key(j["name"], y, num, it.title), title=it.title, journal=j["name"], year=y, issue=num,
                                            date=it.date, authors=it.authors, url=it.url, tier=j.get("tier", ""),
                                            institutions=[]))
                added = upsert(arts, new_arts)
                done[key] = {"status": "ok", "count": len(items), "added": added, "at": today.isoformat()}
                log_rows.append(f"{j['name']} {y}年第{num}期: {len(items)} 篇（新增 {added}）")
                time.sleep(sleep_s)

    # 2) 元数据接口：补作者单位（优先近期、未处理的）
    pending = [a for a in arts.values() if not a.affiliations and a.url and "articleinfo?id=" in a.url and a.year in years]
    pending.sort(key=lambda a: (-a.year, -a.issue))
    detail_ok = detail_fail = 0
    for a in pending:
        if detail_budget <= 0:
            break
        detail_budget -= 1
        m_id = re.search(r"id=([A-Za-z0-9]+)", a.url)
        if not m_id:
            continue
        try:
            meta = fetch_article_meta(m_id.group(1))
        except Exception as exc:  # noqa: BLE001
            log.warning("meta %s failed: %s", a.url, exc)
            detail_fail += 1
            time.sleep(sleep_s * 2)
            continue
        affs = split_organ(str(meta.get("showorgan") or ""))
        if not a.authors and meta.get("showwriter"):
            a.authors = [re.sub(r"\[\d+\]", "", x).strip() for x in re.split(r"[;；]", str(meta["showwriter"])) if x.strip()][:8]
        if affs:
            a.affiliations = affs
            a.institutions = matcher.match_all(affs)
            detail_ok += 1
        else:
            a.affiliations = ["(未解析)"] if meta else ["(接口无数据)"]
            detail_fail += 1
        time.sleep(sleep_s)

    # 3) 重新匹配（单位名录可能更新）
    for a in arts.values():
        if a.affiliations and a.affiliations != ["(未解析)"]:
            a.institutions = matcher.match_all(a.affiliations)
    save_articles(arts)
    st["runs"].append({"date": today.isoformat(), "issue_pages_used": max_issue_pages - issue_budget, "detail_ok": detail_ok,
                       "detail_fail": detail_fail, "articles": len(arts)})
    st["runs"] = st["runs"][-50:]
    save_state(st)
    return {"articles": len(arts), "issue_pages_used": max_issue_pages - issue_budget, "detail_ok": detail_ok, "detail_fail": detail_fail,
            "pending_details": max(0, len(pending) - (max_detail_pages - detail_budget)), "log": log_rows[:80]}
