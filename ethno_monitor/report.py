"""周报渲染：Markdown 与邮件用 HTML。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import markdown

from .config import DIRECTIONS
from .models import Item, SourceStatus


@dataclass
class ReportContext:
    period: str                       # 如 2026年第36周
    today: date
    window_days: int
    new_items: list[Item]
    all_items: list[Item]
    statuses: list[SourceStatus]
    analysis_md: str
    analysis_by: str
    llm_note: str = ""
    extra_notes: list[str] = field(default_factory=list)


def period_label(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}年第{w:02d}周"


def period_slug(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _link(it: Item) -> str:
    return f"[链接]({it.url})" if it.url else ""


def _flag(it: Item) -> str:
    f = []
    if it.guangxi_related:
        f.append("🌿桂")
    if not it.verified:
        f.append("⚠未核实")
    return " ".join(f)


def render_markdown(ctx: ReportContext) -> str:
    papers = [i for i in ctx.new_items if i.kind == "paper"]
    projects = [i for i in ctx.new_items if i.kind == "project"]
    notices = [i for i in ctx.new_items if i.kind == "notice"]
    unverified = [i for i in ctx.new_items if not i.verified]
    gx = [i for i in ctx.new_items if i.guangxi_related and i.kind != "notice"]

    L: list[str] = []
    L.append(f"# 民族学学科监测周报 · {ctx.period}")
    L.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　监测窗口：近 {ctx.window_days} 天　分析引擎：{ctx.analysis_by}")
    L.append("")
    L.append("## 一、本周概览")
    L.append("")
    L.append("| 指标 | 数量 |")
    L.append("|---|---|")
    L.append(f"| 新增论文 | {len(papers)} |")
    L.append(f"| 新增课题立项 | {len(projects)} |")
    L.append(f"| 相关公告 | {len(notices)} |")
    L.append(f"| 涉桂成果/课题 | {len(gx)} |")
    L.append(f"| 待核实条目 | {len(unverified)} |")
    L.append("")
    L.append("| 方向 | 论文 | 课题 |")
    L.append("|---|---|---|")
    for d in DIRECTIONS:
        L.append(f"| {d} | {sum(1 for p in papers if p.direction == d)} | {sum(1 for p in projects if p.direction == d)} |")
    L.append("")

    L.append("## 二、论文监测（按方向）")
    L.append("")
    by_dir: dict[str, list[Item]] = defaultdict(list)
    for p in papers:
        by_dir[p.direction].append(p)
    if not papers:
        L.append("本周未监测到新增论文（请查看文末数据源状态）。")
    for d in DIRECTIONS:
        lst = by_dir.get(d)
        if not lst:
            continue
        L.append(f"### {d}（{len(lst)} 篇）")
        L.append("")
        L.append("| 题目 | 作者 | 期刊 / 期号 | 标记 | 来源 |")
        L.append("|---|---|---|---|---|")
        for p in sorted(lst, key=lambda x: (x.source, x.date), reverse=False):
            issue = p.extra.get("issue") or p.date
            L.append(f"| {p.title} | {'、'.join(p.authors[:4])} | {p.source} {issue} | {_flag(p)} | {_link(p)} |")
        L.append("")

    L.append("## 三、课题立项监测（按资助机构）")
    L.append("")
    by_f: dict[str, list[Item]] = defaultdict(list)
    for p in projects:
        by_f[p.extra.get("funder") or p.source].append(p)
    if not projects:
        L.append("本周未监测到新增民族学相关立项。")
    for f, lst in sorted(by_f.items(), key=lambda kv: -len(kv[1])):
        L.append(f"### {f}（{len(lst)} 项）")
        L.append("")
        L.append("| 课题名称 | 负责人 | 单位 | 类别 | 方向 | 标记 | 来源 |")
        L.append("|---|---|---|---|---|---|---|")
        for p in lst:
            pi = p.extra.get("pi") or "、".join(p.authors[:2])
            L.append(f"| {p.title} | {pi} | {p.affiliation} | {p.extra.get('project_type', '')} | {p.direction} | {_flag(p)} | {_link(p)} |")
        L.append("")
    if notices:
        L.append("### 相关公告 / 通知")
        L.append("")
        for n in sorted(notices, key=lambda x: x.date, reverse=True):
            extra = f"（下钻抽取课题 {n.extra['projects_found']} 项）" if n.extra.get("projects_found") else ""
            L.append(f"- {n.date} 【{n.source}】[{n.title}]({n.url}){extra} {_flag(n)}")
        L.append("")

    L.append("## 四、研究分析与广西特色选题策划")
    L.append("")
    L.append(ctx.analysis_md.strip())
    L.append("")

    L.append("## 五、数据源状态")
    L.append("")
    L.append("| 数据源 | 状态 | 条目 | 说明 | 耗时 |")
    L.append("|---|---|---|---|---|")
    for s in ctx.statuses:
        L.append(f"| {s.name} | {'✅' if s.ok else '❌'} | {s.count} | {s.message.replace('|', '/')} | {s.elapsed:.1f}s |")
    L.append("")
    if ctx.extra_notes:
        for n in ctx.extra_notes:
            L.append(f"> {n}")
        L.append("")
    if unverified:
        L.append("> ⚠ 标记“未核实”的条目仅来自 LLM 联网检索且缺少可核对的来源链接，引用前请到知网/期刊官网核实。")
        L.append("")
    L.append("---")
    L.append("本报告由民族学学科监测系统自动生成。监测范围：民族研究、中华民族共同体研究、中央民族大学学报、西北民族研究、广西民族研究、贵州民族研究、青海民族大学学报、广西民族大学学报、世界民族、青海民族研究等 C 刊；国家社科基金（年度/重大/铸牢中华民族共同体意识研究专项）、国家民委民族研究项目、教育部重大课题攻关项目等立项信息。")
    return "\n".join(L)


CSS = """
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif;font-size:14px;line-height:1.65;color:#222;max-width:1080px;margin:0 auto;padding:16px;background:#fff}
h1{font-size:22px;border-bottom:2px solid #8b1a1a;padding-bottom:6px;color:#8b1a1a}
h2{font-size:18px;margin-top:28px;border-left:4px solid #8b1a1a;padding-left:8px}
h3{font-size:15px;margin-top:18px;color:#333}
table{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:13px}
th,td{border:1px solid #ddd;padding:5px 7px;vertical-align:top;text-align:left}
th{background:#f4ecec}
tr:nth-child(even) td{background:#fafafa}
blockquote{color:#666;border-left:3px solid #ccc;margin:8px 0;padding:4px 10px;background:#f9f9f9}
a{color:#1a5fb4;text-decoration:none}
code{background:#f3f3f3;padding:1px 4px;border-radius:3px}
"""


def to_html(md_text: str, title: str) -> str:
    body = markdown.markdown(md_text, extensions=["tables", "sane_lists", "nl2br"])
    return (f"<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>{title}</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")


# ---------------------------------------------------------------------------
# 观察站网页（GitHub Pages：docs/index.html + docs/reports/*.html）
# ---------------------------------------------------------------------------
SITE_CSS = """
:root{--ground:#f3f5f8;--paper:#ffffff;--ink:#1b2330;--ink-2:#4a5566;--muted:#75808f;--line:#d9dfe7;--indigo:#23395b;--indigo-2:#3b5a86;--bronze:#8c6d3f;--madder:#a63d40;--tint:#e8edf5;--tint-2:#f6f1e7}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--ground:#121820;--paper:#1a2230;--ink:#e6ebf2;--ink-2:#b8c2d0;--muted:#8794a5;--line:#2b3646;--indigo:#9db7dd;--indigo-2:#7f9dc9;--bronze:#c9a86a;--madder:#e0787a;--tint:#22304a;--tint-2:#2a2620}}
:root[data-theme="dark"]{--ground:#121820;--paper:#1a2230;--ink:#e6ebf2;--ink-2:#b8c2d0;--muted:#8794a5;--line:#2b3646;--indigo:#9db7dd;--indigo-2:#7f9dc9;--bronze:#c9a86a;--madder:#e0787a;--tint:#22304a;--tint-2:#2a2620}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:"Noto Sans SC","PingFang SC","Microsoft YaHei","Hiragino Sans GB",sans-serif;font-size:15px;line-height:1.7;font-variant-numeric:tabular-nums}
h1,h2,h3,.display{font-family:"Noto Serif SC","Songti SC","SimSun",serif;text-wrap:balance}
.mast{background:var(--paper);border-bottom:3px solid var(--indigo)}
.mast .wrap{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px 24px;padding:28px 20px 18px}
.mast h1{margin:0;font-size:30px;letter-spacing:.06em;color:var(--indigo)}
.mast .sub{margin:4px 0 0;color:var(--ink-2)}
.mast .eyebrow{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--bronze)}
.mast .issue{text-align:right;color:var(--ink-2);font-size:14px}.mast .issue b{display:block;font-size:20px;color:var(--ink)}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin:22px 0}
.tile{background:var(--paper);padding:14px 16px}
.tile b{display:block;font-size:28px;line-height:1.1;color:var(--indigo);font-family:"Noto Serif SC","Songti SC",serif}.tile span{color:var(--muted);font-size:13px}
.tile.gx b{color:var(--madder)}.tile.warn b{color:var(--bronze)}
.grid{display:grid;grid-template-columns:minmax(0,2.1fr) minmax(260px,1fr);gap:22px;align-items:start}@media(max-width:880px){.grid{grid-template-columns:1fr}}
.card{background:var(--paper);border:1px solid var(--line);padding:18px 22px;margin-bottom:22px}
.card h2{margin:0 0 12px;font-size:19px;color:var(--indigo);padding-bottom:8px;border-bottom:1px solid var(--line)}
.card h3{font-size:15px;margin:16px 0 8px;color:var(--ink)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 12px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}th{background:var(--tint);color:var(--ink-2);font-weight:600;letter-spacing:.04em}
.tablewrap,.report-body table{display:block;overflow-x:auto}
.dir{padding:10px 12px;border-left:3px solid var(--indigo);background:var(--tint);margin-bottom:10px}.dir b{color:var(--indigo)}.dir .n{float:right;color:var(--muted);font-size:13px}
.dir p{margin:4px 0 0;color:var(--ink-2);font-size:13px;line-height:1.55}
.list{margin:0;padding-left:18px}.list li{margin:4px 0}.muted{color:var(--muted);font-size:13px}
a{color:var(--indigo-2);text-decoration:none}a:hover{text-decoration:underline}a:focus-visible{outline:2px solid var(--bronze);outline-offset:2px}
.report-body h1{display:none}.report-body h2{font-size:18px;margin-top:26px;color:var(--indigo)}.report-body h3{font-size:15px;margin-top:18px}
.report-body blockquote{color:var(--ink-2);border-left:3px solid var(--bronze);margin:8px 0;padding:6px 12px;background:var(--tint-2)}
.focus{background:var(--tint-2);border-left:3px solid var(--bronze)}
footer{color:var(--muted);font-size:13px;padding:26px 20px 34px;border-top:1px solid var(--line);margin-top:8px}
@media (prefers-reduced-motion: no-preference){.tile b{transition:color .2s}}
"""


def _latest_slug(report_dir) -> str:
    slugs = sorted(p.stem for p in report_dir.glob("????-W??.md"))
    return slugs[-1] if slugs else ""


def render_site(report_dir, docs_dir, settings) -> str:
    """生成 docs/index.html 观察站首页，并把各期 HTML 复制到 docs/reports/；同时生成 docs/observatory.artifact.html（Artifact 用）。返回首页路径。"""
    import json
    import shutil
    from pathlib import Path

    report_dir, docs_dir = Path(report_dir), Path(docs_dir)
    (docs_dir / "reports").mkdir(parents=True, exist_ok=True)
    slugs = sorted((p.stem for p in report_dir.glob("????-W??.md")), reverse=True)
    for s in slugs:
        src = report_dir / f"{s}.html"
        if src.exists():
            shutil.copyfile(src, docs_dir / "reports" / f"{s}.html")
    latest = slugs[0] if slugs else ""
    stats = {"paper": 0, "project": 0, "notice": 0, "gx": 0, "unverified": 0}
    by_dir = {d: 0 for d in DIRECTIONS}
    if latest and (report_dir / f"{latest}.items.json").exists():
        for d in json.loads((report_dir / f"{latest}.items.json").read_text(encoding="utf-8")):
            stats[d.get("kind", "paper")] = stats.get(d.get("kind", "paper"), 0) + 1
            if d.get("guangxi_related") and d.get("kind") != "notice":
                stats["gx"] += 1
            if not d.get("verified", True):
                stats["unverified"] += 1
            if d.get("direction") in by_dir and d.get("kind") != "notice":
                by_dir[d["direction"]] += 1
    latest_html = ""
    if latest:
        md = (report_dir / f"{latest}.md").read_text(encoding="utf-8")
        latest_html = markdown.markdown(md, extensions=["tables", "sane_lists", "nl2br"])
    journals = [j["name"] for j in settings.sources.get("journals", [])]
    funders = sorted({n.get("funder", n["name"]) for n in settings.sources.get("notice_sources", [])} | {"国家社科基金重大项目", "国家社科基金铸牢中华民族共同体意识研究专项"})
    dirs_html = "".join(
        f'<div class="dir"><span class="n">{by_dir[d]} 条</span><b>{d}</b>'
        f'<p>{((settings.keywords.get("directions") or {}).get(d) or {}).get("description", "")}</p></div>' for d in DIRECTIONS)
    region = settings.guangxi.get("region", {})
    focus = [t for t in region.get("nanling_corridor", {}).get("themes", [])[:3]] + [t for t in region.get("southeast_asia", {}).get("themes", [])[:3]]
    focus_html = "".join(f"<li>{t}</li>" for t in focus)
    groups = "、".join(g["name"] for g in region.get("twelve_ethnic_groups", []))
    archive_html = "".join(f'<li><a href="reports/{s}.html">{s[:4]}年第{int(s[6:]):02d}周周报</a></li>' for s in slugs) or "<li class='muted'>暂无</li>"
    label = f"{latest[:4]}年第{int(latest[6:]):02d}周" if latest else "尚未生成"
    positioning = region.get("positioning", [])[:2]
    body = f"""
<header class="mast"><div class="wrap">
<div><div class="eyebrow">Guangxi Ethnology Observatory · 每周一更新</div><h1>广西民族学观察站</h1>
<p class="sub">民族学学科四方向 · 民族学类 C 刊论文与国家级课题立项监测 · 广西特色选题策划</p></div>
<div class="issue">最新一期<b>{label}</b></div>
</div></header>
<div class="wrap">
<div class="tiles">
<div class="tile"><b>{stats['paper']}</b><span>本期新增论文</span></div>
<div class="tile"><b>{stats['project']}</b><span>本期新增课题立项</span></div>
<div class="tile"><b>{stats['notice']}</b><span>相关公告</span></div>
<div class="tile gx"><b>{stats['gx']}</b><span>涉桂成果 / 课题</span></div>
<div class="tile warn"><b>{stats['unverified']}</b><span>待核实条目</span></div>
</div>
<div class="grid">
<main>
<div class="card"><h2>最新周报 · {label}</h2><div class="report-body">{latest_html or '<p class="muted">尚未生成周报。</p>'}</div></div>
</main>
<aside>
<div class="card"><h2>四个学科方向</h2>{dirs_html}</div>
<div class="card focus"><h2>广西区域聚焦</h2><p class="muted">{'；'.join(positioning)}</p><p class="muted">十二个世居民族：{groups}</p><ul class="list">{focus_html}</ul></div>
<div class="card"><h2>监测期刊</h2><ul class="list">{''.join(f'<li>{j}</li>' for j in journals)}</ul></div>
<div class="card"><h2>监测课题来源</h2><ul class="list">{''.join(f'<li>{f}</li>' for f in funders)}</ul></div>
<div class="card"><h2>往期周报</h2><ul class="list">{archive_html}</ul></div>
</aside>
</div></div>
<footer><div class="wrap">民族学学科监测系统自动生成。数据来自全国哲学社会科学工作办公室、国家民委、教育部社科司、国家社科基金项目数据库、期刊官网及联网检索；标记"待核实"的条目引用前请核对原文。仓库：<a href="https://github.com/BenHaoz/cfll-gemini">BenHaoz/cfll-gemini</a></div></footer>"""
    fonts = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700&family=Noto+Sans+SC:wght@400;500;700&display=swap">'
    html = (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>广西民族学观察站</title>{fonts}<style>{SITE_CSS}</style></head><body>{body}</body></html>')
    (docs_dir / "observatory.artifact.html").write_text(f"<title>广西民族学观察站</title>\n{fonts}\n<style>{SITE_CSS}</style>\n{body}", encoding="utf-8")
    out = docs_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return str(out)
