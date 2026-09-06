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
            for sel in f.find_all("select")[:6]:
                opts = [f"{o.get('value')}={clean(o.get_text())[:12]}" for o in sel.find_all("option")[:30]]
                lines.append(f"    select {sel.get('name')}: {' | '.join(opts)}")
    if not anchors:
        text = clean(soup.get_text(" "))
        lines.append(f"  页面正文前 300 字: {text[:300]!r}")
    return "\n".join(lines)


def probe_page(url: str) -> str:
    """深度探测：脚本地址、内联脚本中的接口地址、文章条目原始 HTML（用于发现数据接口与字段）。"""
    lines = [f"### PROBE {url}"]
    try:
        resp = fetch(url, timeout=25, retries=1)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"  !! 请求失败: {str(exc)[:200]}")
        return "\n".join(lines)
    html = fix_encoding(resp)
    soup = soup_of(html)
    srcs = [s.get("src") for s in soup.find_all("script", src=True)]
    lines.append("  script src: " + " | ".join(str(x)[:100] for x in srcs[:15]))
    inline = "\n".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))
    hits = re.findall(r"""(?:url|ajax|axios|fetch|post|get)\s*[:(]\s*['"`]([^'"`]{4,140})['"`]""", inline, flags=re.I)
    uniq = []
    for h in hits:
        if h not in uniq:
            uniq.append(h)
    lines.append("  内联接口候选: " + " | ".join(uniq[:30]))
    fn = re.findall(r"""function\s+(\w*(?:detail|Detail|article|Article|list|List|search|Search)\w*)\s*\(([^)]*)\)\s*\{(.{0,300})""", inline, flags=re.S)
    for name, args, body in fn[:6]:
        lines.append(f"  函数 {name}({args}): {clean(body)[:260]}")
    n = 0
    detail_url = ""
    for a in soup.find_all("a", href=True):
        if a["href"].strip().lower().startswith("javascript") and len(clean(a.get_text())) >= 8:
            li = a.find_parent(["p", "li", "tr", "div"])
            lines.append("  条目HTML: " + re.sub(r"\s+", " ", str(li or a))[:500])
            m = re.search(r"openDetail\('([^']+)'", a.get("onclick") or "")
            if m and not detail_url:
                detail_url = m.group(1).replace("&amp;", "&")
            n += 1
            if n >= 1:
                break
    # 文献详情页：看作者/机构字段如何呈现
    if detail_url:
        for host in ("https://m.ncpssd.cn", "https://www.ncpssd.cn"):
            try:
                r2 = fetch(host + detail_url, timeout=25, retries=1)
                h2 = fix_encoding(r2)
                s2 = soup_of(h2)
                for t in s2.find_all(["script", "style"]):
                    t.decompose()
                txt = clean(s2.get_text(" "))
                lines.append(f"  详情页 {host}: status={r2.status_code} bytes={len(r2.content)} 正文前600字: {txt[:600]!r}")
                for kw in ("作者", "机构", "单位", "Author", "作者单位"):
                    i = h2.find(kw)
                    if i != -1:
                        lines.append(f"  详情页HTML@{kw}: " + re.sub(r"\s+", " ", h2[max(0, i - 200): i + 700]))
                        break
            except Exception as exc:  # noqa: BLE001
                lines.append(f"  详情页 {host} 失败: {str(exc)[:120]}")
    # 按年/期切换探测
    m = re.search(r"gch=(\w+)", url)
    if m:
        for test in (f"https://m.ncpssd.cn/journal/details?gch={m.group(1)}&years=2025&num=6&nav=1&langType=1",
                     f"https://m.ncpssd.cn/journal/details?gch={m.group(1)}&years=2025&num=1&nav=1&langType=1"):
            try:
                r3 = fetch(test, timeout=25, retries=1)
                s3 = soup_of(fix_encoding(r3))
                cat = s3.find("div", class_="catalog")
                head = clean(cat.find("h2").get_text(" ")) if cat and cat.find("h2") else ""
                cnt = len([x for x in s3.find_all("a", onclick=True) if "openDetail" in x.get("onclick", "")])
                lines.append(f"  按期切换 {test[-45:]}: h2={head!r} 文章锚点={cnt}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"  按期切换失败: {str(exc)[:120]}")
        # 期刊总录：年份/期号列表
        tot = soup.find(id="journalTotal")
        if tot:
            lines.append("  期刊总录HTML: " + re.sub(r"\s+", " ", str(tot))[:900])
    return "\n".join(lines)


def diagnose(settings) -> str:
    src = settings.sources
    out = ["", "================ 数据源诊断 ================"]
    for ns in src.get("notice_sources", []):
        out.append(f"\n## 公告源：{ns['name']}")
        for u in ns.get("urls", []):
            out.append(_diag_url(u, link_regex=ns.get("link_regex", "")))
    probed = 0
    for j in src.get("journals", []):
        for pg in j.get("toc_pages") or []:
            out.append(f"\n## 期刊目录：{j['name']}")
            out.append(_diag_url(pg["url"]))
            if probed < 2:
                out.append(probe_page(pg["url"]))
                probed += 1
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
