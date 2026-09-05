"""LLM 联网检索兜底：逐刊检索最新目录、检索最新立项公告，输出带来源链接的结构化条目。"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from ..llm import LLMClient, extract_json
from ..models import Item, SourceStatus
from .base import clean, parse_date

log = logging.getLogger(__name__)

SYSTEM = (
    "你是民族学学科文献与科研项目情报员。你必须依据检索到的网页内容作答，"
    "严禁编造论文、作者、课题或人名；不确定的字段留空字符串。只输出 JSON 数组，不要输出其他文字。"
)

JOURNAL_PROMPT = """请用搜索工具查找学术期刊《{journal}》{year}年最新一期（以及若能找到的前一期）的目录。
返回 JSON 数组，每个元素形如：
{{"title": "文章标题", "authors": ["作者1", "作者2"], "issue": "{year}年第X期", "date": "YYYY-MM", "url": "来源网页链接", "summary": "一句话主题（可留空）"}}
要求：
1. 只收录你在网页中实际看到的文章条目，不要凭记忆补全；
2. 优先来源：期刊官网、知网（cnki.net）、国家哲学社会科学文献中心（ncpssd.cn）、中国社会科学网、期刊公众号转载页；
3. 最多 30 条；找不到任何内容时返回 []。"""

PROJECT_PROMPT = """请用搜索工具查找以下主题的最新官方公告或高校科研处转载：{query}
关注时间范围：最近 {days} 天（今天是 {today}）。若最近无新公告，可放宽到本年度内，但请在 date 字段如实填写公告日期。
返回 JSON 数组，每个元素形如：
{{"title": "课题/项目名称", "pi": "负责人", "unit": "单位", "funder": "资助机构/项目类别（如：国家社科基金重大项目、国家民委民族研究项目重点项目）", "type": "重点/一般/青年/重大/专项", "date": "YYYY-MM-DD", "url": "公告链接", "notice": "公告标题"}}
要求：
1. 只收录与民族学（含四个方向：马克思主义民族理论与政策、中华民族学、人类学与世界民族、中华民族共同体学）相关的课题；若公告是完整名单而条目过多，只列民族学相关的，最多 40 条；
2. 若只找到公告本身而看不到具体名单，可返回一条 title 为公告标题、type 为"公告"的记录；
3. 找不到任何内容时返回 []。"""


def _as_list(x: Any) -> list[str]:
    if isinstance(x, list):
        return [clean(str(i)) for i in x if clean(str(i))]
    if isinstance(x, str) and x.strip():
        import re
        return [t for t in re.split(r"[、,，;；\s/]+", x) if t]
    return []


def collect_llm_journals(client: LLMClient, journals: list[dict[str, Any]], *, year: int, budget: int) -> tuple[list[Item], SourceStatus]:
    t0 = time.time()
    items: list[Item] = []
    fails = 0
    used = 0
    for j in journals:
        if used >= budget:
            break
        used += 1
        jname = j["name"]
        try:
            res = client.research(JOURNAL_PROMPT.format(journal=jname, year=year), system=SYSTEM)
            data = extract_json(res.text)
        except Exception as exc:  # noqa: BLE001
            log.warning("llm journal %s failed: %s", jname, exc)
            fails += 1
            continue
        if not isinstance(data, list):
            fails += 1
            continue
        for rec in data:
            if not isinstance(rec, dict):
                continue
            title = clean(str(rec.get("title", "")))
            if len(title) < 4:
                continue
            url = clean(str(rec.get("url", "")))
            evidence = ([url] if url.startswith("http") else []) + [u for u in res.urls[:3] if u != url]
            items.append(Item(kind="paper", title=title, url=url if url.startswith("http") else (res.urls[0] if res.urls else ""),
                              source=jname, date=parse_date(str(rec.get("date", ""))) or parse_date(str(rec.get("issue", ""))),
                              authors=_as_list(rec.get("authors"))[:6], verified=bool(evidence),
                              evidence=evidence[:4],
                              extra={"issue": clean(str(rec.get("issue", ""))), "summary": clean(str(rec.get("summary", "")))[:200], "via": "llm"}))
    ok = fails < max(1, used)
    return items, SourceStatus(name=f"LLM联网检索·期刊目录（{client.name}）", ok=ok, count=len(items),
                               message=f"{used - fails}/{used} 刊成功，{len(items)} 篇", elapsed=time.time() - t0, kind="llm")


def collect_llm_projects(client: LLMClient, queries: list[str], *, today: date, lookback_days: int, budget: int) -> tuple[list[Item], SourceStatus]:
    t0 = time.time()
    items: list[Item] = []
    fails = 0
    used = 0
    for q in queries:
        if used >= budget:
            break
        used += 1
        query = q.replace("{year}", str(today.year))
        try:
            res = client.research(PROJECT_PROMPT.format(query=query, days=lookback_days, today=today.isoformat()), system=SYSTEM)
            data = extract_json(res.text)
        except Exception as exc:  # noqa: BLE001
            log.warning("llm project query failed: %s", exc)
            fails += 1
            continue
        if not isinstance(data, list):
            fails += 1
            continue
        for rec in data:
            if not isinstance(rec, dict):
                continue
            title = clean(str(rec.get("title", "")))
            if len(title) < 4:
                continue
            url = clean(str(rec.get("url", "")))
            evidence = ([url] if url.startswith("http") else []) + [u for u in res.urls[:3] if u != url]
            ptype = clean(str(rec.get("type", "")))
            kind = "notice" if ptype == "公告" else "project"
            pi = clean(str(rec.get("pi", "")))
            items.append(Item(kind=kind, title=title, url=url if url.startswith("http") else (res.urls[0] if res.urls else ""),
                              source=clean(str(rec.get("funder", ""))) or "LLM检索", date=parse_date(str(rec.get("date", ""))),
                              authors=[pi] if pi else [], affiliation=clean(str(rec.get("unit", ""))), verified=bool(evidence),
                              evidence=evidence[:4],
                              extra={"funder": clean(str(rec.get("funder", ""))), "project_type": ptype, "pi": pi,
                                     "from_notice": clean(str(rec.get("notice", ""))), "via": "llm", "query": query}))
    ok = fails < max(1, used)
    return items, SourceStatus(name=f"LLM联网检索·课题立项（{client.name}）", ok=ok, count=len(items),
                               message=f"{used - fails}/{used} 查询成功，{len(items)} 条", elapsed=time.time() - t0, kind="llm")
