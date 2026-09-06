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
        for host in ("https://www.ncpssd.cn", "https://m.ncpssd.cn"):
            try:
                r2 = fetch(host + detail_url, timeout=25, retries=1)
                h2 = fix_encoding(r2)
                s2 = soup_of(h2)
                for t in s2.find_all(["script", "style"]):
                    t.decompose()
                txt = clean(s2.get_text(" "))
                lines.append(f"  详情页 {host}: status={r2.status_code} bytes={len(r2.content)} 正文长度={len(txt)}")
                # 作者名附近的 HTML（作者串来自列表页 AddHandleCount 参数）
                first_author = ""
                ma = re.search(r"AddHandleCount\([^)]*?'([^']*\[\d\][^']*)'\s*,\s*'[^']*'\s*\)", html)
                if ma:
                    first_author = re.sub(r"\[\d+\].*", "", ma.group(1)).strip()
                for kw in ([first_author] if first_author else []) + ["作者单位", "机构", "[1]", "单位"]:
                    if not kw:
                        continue
                    i = h2.find(kw, 3000)  # 跳过导航区
                    if i != -1:
                        lines.append(f"  详情页HTML@{kw}: " + re.sub(r"\s+", " ", h2[max(0, i - 300): i + 900]))
                        break
                j = txt.find(first_author) if first_author else -1
                if j != -1:
                    lines.append(f"  详情页正文@作者: {txt[max(0, j - 100): j + 500]!r}")
                # 详情页内联脚本中的接口地址与请求参数（文章元数据多为 AJAX 加载）
                inline2 = "\n".join(sc.get_text() for sc in soup_of(h2).find_all("script") if not sc.get("src"))
                cands = []
                for mm in re.finditer(r"""(?:url|post|get|axios\.\w+|\$\.\w+)\s*[:(]\s*['"`]([^'"`]{4,140})['"`]""", inline2, flags=re.I):
                    if mm.group(1) not in cands:
                        cands.append(mm.group(1))
                lines.append("  详情页内联接口候选: " + " | ".join(cands[:40]))
                for mm in list(re.finditer(r"(articleinfo|ArticleInfo|getArticle|articleHandler|literature)\w*", inline2))[:8]:
                    a0 = max(0, mm.start() - 160)
                    lines.append("  详情页脚本片段: " + re.sub(r"\s+", " ", inline2[a0: mm.end() + 240]))
                # 打印含 id 参数的脚本片段
                mid = re.search(r"id\s*[:=]\s*['\"]?" + re.escape(re.search(r"id=([A-Za-z0-9]+)", detail_url).group(1) if re.search(r"id=([A-Za-z0-9]+)", detail_url) else "XXXX"), inline2)
                if mid:
                    a0 = max(0, mid.start() - 400)
                    lines.append("  详情页脚本@id: " + re.sub(r"\s+", " ", inline2[a0: mid.end() + 400]))
                # 内联脚本概览与路径字符串
                sp2 = soup_of(h2)
                inl = [sc.get_text() for sc in sp2.find_all("script") if not sc.get("src")]
                lines.append(f"  详情页内联脚本 {len(inl)} 段；外链脚本 {len(sp2.find_all('script', src=True))} 个")
                for k, sc in enumerate(inl[:12]):
                    t = re.sub(r"\s+", " ", sc.strip())
                    if len(t) > 40:
                        lines.append(f"    内联#{k} len={len(t)}: {t[:240]}")
                paths = sorted({m.group(1) for sc in inl for m in re.finditer(r"""['"](/[A-Za-z][A-Za-z0-9_]*/[A-Za-z0-9_/.]+)['"]""", sc)})
                lines.append("  详情页内联路径: " + " | ".join(paths[:60]))
                for k, mm in enumerate(re.finditer(r"\[1\]", h2)):
                    if k >= 4:
                        break
                    lines.append("  详情页[1]上下文: " + re.sub(r"\s+", " ", h2[max(0, mm.start() - 250): mm.end() + 250]))
                # 外链脚本中的接口地址（文章元数据接口多在外部 JS 中定义）
                if host.startswith("https://www"):
                    from urllib.parse import urljoin
                    srcs2 = [urljoin(host + detail_url, sc["src"]) for sc in soup_of(h2).find_all("script", src=True)]
                    found: dict[str, str] = {}
                    lines.append("  详情页外链脚本: " + " | ".join(x[-60:] for x in srcs2[:20]))
                    for su in srcs2[:20]:
                        if "ncpssd.cn" not in su:
                            continue
                        try:
                            js = fix_encoding(fetch(su, timeout=20, retries=0))
                        except Exception as exc:  # noqa: BLE001
                            lines.append(f"  外链脚本抓取失败 {su[-50:]}: {str(exc)[:60]}")
                            continue
                        lines.append(f"  外链脚本 {su[-50:]} len={len(js)} Literature出现={js.count('Literature')} articleinfo出现={js.lower().count('articleinfo')}")
                        for mm in re.finditer(r"(/(?:Literature|journal|article|literature|api)/[A-Za-z0-9_/]+)", js):
                            ep = mm.group(1)
                            if ep not in found:
                                a0 = max(0, mm.start() - 120)
                                found[ep] = f"{su.rsplit('/', 1)[-1]}: " + re.sub(r"\s+", " ", js[a0: mm.end() + 160])
                    for ep, ctx in list(found.items())[:40]:
                        lines.append(f"  外链脚本接口 {ep} <= {ctx[:320]}")
                    try:
                        js = fix_encoding(fetch("https://www.ncpssd.cn/js/web/Literature/articleinfo.js", timeout=20, retries=0))
                        handlers = sorted({m.group(1) for m in re.finditer(r"""['"]([^'"\s]*Handler[^'"\s]*)['"]""", js)})
                        lines.append("  articleinfo.js Handler字串: " + " | ".join(handlers[:40]))
                        urls = sorted({m.group(1) for m in re.finditer(r"""url\s*:\s*['"]([^'"]+)['"]""", js)})
                        lines.append("  articleinfo.js url: " + " | ".join(urls[:40]))
                        calls = [re.sub(r"\s+", " ", js[max(0, m.start() - 200): m.end() + 500]) for m in re.finditer(r"""(?:\$\.(?:ajax|post|get)|axios\.(?:post|get)|axios)\s*\(""", js)]
                        for c in calls[:6]:
                            lines.append("  articleinfo.js 调用: " + c[:700])
                        m0 = re.search(r"jsons\s*=", js) or re.search(r"jsons\[0\]", js)
                        if m0:
                            lines.append("  articleinfo.js jsons上下文: " + re.sub(r"\s+", " ", js[max(0, m0.start() - 900): m0.end() + 300]))
                        for kw in ("organ", "unit", "dw", "affili", "机构", "单位"):
                            i2 = js.find(kw)
                            if i2 != -1:
                                lines.append(f"  articleinfo.js @{kw}: " + re.sub(r"\s+", " ", js[max(0, i2 - 300): i2 + 300]))
                    except Exception as exc:  # noqa: BLE001
                        lines.append(f"  articleinfo.js 抓取失败: {str(exc)[:80]}")
                    continue
                break  # m 站探测完成后继续探测 www 站的外链脚本
            except Exception as exc:  # noqa: BLE001
                lines.append(f"  详情页 {host} 失败: {str(exc)[:120]}")
    # 候选元数据接口直连尝试
    aid = re.search(r"id=([A-Za-z0-9]+)", detail_url or "")
    if aid:
        art_id = aid.group(1)
        tries = [
            ("POST", "https://www.ncpssd.cn/Literature/articleinfoHandler", {"id": art_id, "type": "journalArticle"}),
            ("POST", "https://www.ncpssd.cn/Literature/articleHandler", {"id": art_id, "type": "journalArticle"}),
            ("POST", "https://www.ncpssd.cn/Literature/getArticleInfo", {"id": art_id, "type": "journalArticle"}),
            ("GET", "https://www.ncpssd.cn/Literature/getArticleInfo", {"id": art_id, "type": "journalArticle"}),
            ("POST", "https://www.ncpssd.cn/Literature/articleinfo", {"id": art_id, "type": "journalArticle"}),
        ]
        for method, u, params in tries:
            try:
                r4 = fetch(u, method=method, data=params if method == "POST" else None, params=params if method == "GET" else None,
                           timeout=20, retries=0, headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.ncpssd.cn/"})
                body = fix_encoding(r4)
                lines.append(f"  接口尝试 {method} {u}: status={r4.status_code} len={len(body)} ctype={r4.headers.get('content-type','')[:40]} head={body[:300]!r}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"  接口尝试 {method} {u}: 失败 {str(exc)[:80]}")
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
        try:
            params_prev = dict(params, lxtime=str(date.today().year - 1))   # 上一年度有数据，便于观察分页
            r = fetch(sk["url"], params=params_prev, timeout=25, retries=1)
            sp = soup_of(fix_encoding(r))
            rows = [tr for tr in sp.find_all("tr") if len(tr.find_all("td")) >= 6]
            out.append(f"  [{params_prev['lxtime']} 年] 页面字节={len(r.content)}")
            pag = sp.find_all(string=re.compile(r"下一页|末页|共\s*\d+"))
            out.append("  分页文本: " + " | ".join(clean(str(x))[:40] for x in pag[:6]))
            for a in sp.find_all("a", href=True)[:60]:
                t = clean(a.get_text())
                if re.fullmatch(r"\d{1,3}|下一页|末页|>|>>", t):
                    out.append(f"  分页锚点 {t} -> {a['href'][-120:]}")
            for f in sp.find_all("form")[:3]:
                hid = [(i.get("name"), i.get("value")) for i in f.find_all("input", type="hidden")]
                if hid:
                    out.append(f"  表单隐藏字段: {hid[:10]}")
            for combo in ({"xktype": "民族学", "lxtime": "2024"}, {"xktype": "民族学", "lxtime": "2025"}, {"xktype": "民族学", "lxtime": "2026"},
                          {"xktype": "民族学", "lxtime": "2025", "p": "2"}, {"xktype": "民族学", "lxtime": "2025", "page": "2"}, {"xktype": "民族学", "lxtime": "2025", "pageNum": "2"}):
                try:
                    rc = fetch(sk["url"], params=dict(params, **combo), timeout=25, retries=0)
                    spc = soup_of(fix_encoding(rc))
                    rowsc = [tr for tr in spc.find_all("tr") if len(tr.find_all("td")) >= 6]
                    first = clean(rowsc[1].get_text(" "))[:120] if len(rowsc) > 1 else ""
                    out.append(f"  组合 {combo}: 字节={len(rc.content)} 数据行={len(rowsc)} 首行={first!r}")
                except Exception as exc:  # noqa: BLE001
                    out.append(f"  组合 {combo}: 失败 {str(exc)[:80]}")
            r2 = fetch(sk["url"], params=dict(params_prev, p=2), timeout=25, retries=1)
            sp2 = soup_of(fix_encoding(r2))
            rows2 = [tr for tr in sp2.find_all("tr") if len(tr.find_all("td")) >= 6]
            same = (rows and rows2 and clean(rows[1].get_text()) == clean(rows2[1].get_text())) if (len(rows) > 1 and len(rows2) > 1) else None
            out.append(f"  p=2 数据行={len(rows2)} 与第一页首行相同={same}")
            out.append(f"  数据行（td>=6）={len(rows)}；前 3 行：")
            for tr in rows[:3]:
                out.append("    | " + " | ".join(clean(td.get_text(" "))[:30] for td in tr.find_all("td")))
            pg = [a for a in sp.find_all("a", href=True) if re.fullmatch(r"\d+|下一页|末页|>|>>", clean(a.get_text()))]
            out.append("  分页链接样例: " + " | ".join(f"{clean(a.get_text())}->{a['href'][-80:]}" for a in pg[:5]))
            onclicks = [t.get("onclick") for t in sp.find_all(attrs={"onclick": True})][:5]
            out.append("  onclick 样例: " + " | ".join(str(o)[:100] for o in onclicks))
            total = re.search(r"共\s*(\d+)\s*[条页]", clean(sp.get_text(" ")))
            out.append(f"  总数提示: {total.group(0) if total else '未找到'}")
        except Exception as exc:  # noqa: BLE001
            out.append(f"  数据行探测失败: {str(exc)[:120]}")
    nc = src.get("ncpssd", {})
    out.append("\n## 国家哲学社会科学文献中心")
    out.append(_diag_url("https://www.ncpssd.cn/"))
    out.append(_diag_url(nc.get("search_url", "https://www.ncpssd.cn/Literature/articlelist")))
    # 核心期刊编号核验：抓取每个 gch / candidate_gch 的期刊页，打印页面刊名与首篇文章
    try:
        import yaml
        from .config import CONFIG_DIR
        core = yaml.safe_load(open(CONFIG_DIR / "journals_core.yaml", encoding="utf-8")) or {}
        out.append("\n## 核心期刊编号核验（journals_core.yaml + theme_journals）")
        to_check = list(core.get("journals", []))
        for tj in src.get("theme_journals", []) or []:
            for pg in tj.get("toc_pages") or []:
                mm = re.search(r"gch=(\w+)", pg["url"])
                if mm:
                    to_check.append({"name": f"[专题]{tj['name']}", "gch": mm.group(1)})
        for j in to_check:
            for code, kind in ((j.get("gch"), "gch"), (j.get("candidate_gch"), "candidate")):
                if not code:
                    continue
                u = f"https://m.ncpssd.cn/journal/details?gch={code}&nav=1&langType=1"
                try:
                    r = fetch(u, timeout=25, retries=1)
                    sp = soup_of(fix_encoding(r))
                    for t in sp.find_all(["script", "style"]):
                        t.decompose()
                    txt = clean(sp.get_text(" "))
                    i = txt.find("刊名")
                    name_hint = txt[i:i + 40] if i != -1 else ""
                    h = sp.find(["h1", "h3"])
                    head = clean(h.get_text(" "))[:40] if h else ""
                    issn = re.search(r"ISSN[:：]?\s*([0-9]{4}-[0-9Xx]{4})", txt)
                    zb = txt.find("主办")
                    name_hint = (f"ISSN={issn.group(1)} " if issn else "") + (txt[zb: zb + 40] if zb != -1 else "")
                    dt = sp.find(class_=re.compile("journal|qk|name|tit", re.I))
                    head = head or (clean(dt.get_text(" "))[:40] if dt else "")
                    cat = sp.find("div", class_="catalog")
                    first = ""
                    if cat:
                        a = cat.find("a", onclick=True)
                        first = clean(a.get_text())[:40] if a else ""
                        issue = clean(cat.find("h2").get_text(" "))[:20] if cat.find("h2") else ""
                    else:
                        issue = ""
                    out.append(f"  {j['name']} [{kind}={code}] head={head!r} 刊名字段={name_hint!r} 当期={issue!r} 首篇={first!r}")
                except Exception as exc:  # noqa: BLE001
                    out.append(f"  {j['name']} [{kind}={code}] 失败: {str(exc)[:100]}")
    except Exception as exc:  # noqa: BLE001
        out.append(f"  核验跳过: {exc}")
    out.append("============================================")
    return "\n".join(out)
