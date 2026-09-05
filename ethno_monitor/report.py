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
