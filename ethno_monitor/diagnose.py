"""数据源诊断：打印各来源页面的可达性与结构摘要，便于通过 CI 日志远程校正选择器/正则。"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from .collectors.base import CJK, clean, soup_of
from .http import fetch, fix_encoding


def _diag_url(url: str, *, params: dict[str, Any] | None = None, link_regex: str = "") -> str:
    lines = [f"### {url}"]
    try:
        resp = fetch(url, params=params, timeout=25, retries=1)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"  !! 请求失败: {str(exc)[:200]}")
        return "\n".join(lines)
    html = fix_encoding(resp)
    soup = soup_of(html)
    title = clean(soup.title.get_text()) if soup.title else ""
    lines.append(f"  status={resp.status_code} final={resp.url} enc={resp.encoding} bytes={len(resp.content)} title={title[:60]!r}")
    anchors = [a for a in soup.find_all("a", href=True) if CJK.search(clean(a.get_text(" ")) or "")]
    lines.append(f"  中文锚点数={len(anchors)} 表格数={len(soup.find_all('table'))} li数={len(soup.find_all('li'))}")
    pat = re.compile(link_regex) if link_regex else None
    matched = 0
    for a in anchors[:400]:
        href = urljoin(url, a["href"])
        if pat and pat.search(href):
            matched += 1
    if pat:
        lines.append(f"  link_regex 命中={matched}")
    lines.append("  样例锚点（最多 12 条）：")
    shown = 0
    for a in anchors:
        t = clean(a.get_text(" "))
        if len(t) < 8:
            continue
        lines.append(f"    - {t[:50]} -> {urljoin(url, a['href'])[:120]}")
        shown += 1
        if shown >= 12:
            break
    tables = soup.find_all("table")
    if tables:
        big = max(tables, key=lambda t: len(t.find_all("tr")))
        rows = big.find_all("tr")
        lines.append(f"  最大表格 {len(rows)} 行，前 4 行：")
        for tr in rows[:4]:
            lines.append("    | " + " | ".join(clean(td.get_text(" "))[:24] for td in tr.find_all(["td", "th"]))[:200])
    forms = soup.find_all("form")
    if forms and not anchors:
        for f in forms[:2]:
            names = [i.get("name") for i in f.find_all(["input", "select"]) if i.get("name")]
            lines.append(f"  表单 action={f.get('action')} method={f.get('method')} 字段={names[:20]}")
    if not anchors:
        text = clean(soup.get_text(" "))
        lines.append(f"  页面正文前 300 字: {text[:300]!r}")
    return "\n".join(lines)


def diagnose(settings) -> str:
    src = settings.sources
    out = ["", "================ 数据源诊断 ================"]
    for ns in src.get("notice_sources", []):
        out.append(f"\n## 公告源：{ns['name']}")
        for u in ns.get("urls", []):
            out.append(_diag_url(u, link_regex=ns.get("link_regex", "")))
    for j in src.get("journals", []):
        for pg in j.get("toc_pages") or []:
            out.append(f"\n## 期刊目录：{j['name']}")
            out.append(_diag_url(pg["url"]))
    sk = src.get("skygb", {})
    if sk.get("enabled", True):
        out.append("\n## 国家社科基金项目数据库")
        from datetime import date
        params = {k: (str(v).replace("{year}", str(date.today().year)) if isinstance(v, str) else v) for k, v in (sk.get("params") or {}).items()}
        out.append(_diag_url(sk["url"], params=dict(params, p=1)))
    nc = src.get("ncpssd", {})
    out.append("\n## 国家哲学社会科学文献中心")
    out.append(_diag_url("https://www.ncpssd.cn/"))
    out.append(_diag_url(nc.get("search_url", "https://www.ncpssd.cn/Literature/articlelist")))
    out.append("============================================")
    return "\n".join(out)
