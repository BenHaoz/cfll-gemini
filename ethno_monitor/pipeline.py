"""主流程：采集 -> 分类过滤 -> 去重与新增判定 -> 分析 -> 渲染 -> 邮件 -> 状态保存。"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from .analysis import analyze
from .classify import Classifier
from .collectors.journals import collect_journal_toc, collect_ncpssd
from .collectors.llm_research import collect_llm_journals, collect_llm_projects
from .collectors.notices import collect_notice_source
from .collectors.rss import collect_rss
from .collectors.skygb import collect_skygb
from .config import REPORT_DIR, ROOT, Settings
from .llm import make_client
from .mailer import send_mail
from .models import Item, SourceStatus
from .report import ReportContext, period_label, period_slug, render_markdown, to_html
from .state import State

log = logging.getLogger(__name__)


def collect_all(settings: Settings, *, today: date, use_llm: bool, only: str | None = None) -> tuple[list[Item], list[SourceStatus]]:
    src = settings.sources
    lb = settings.lookback_days
    items: list[Item] = []
    statuses: list[SourceStatus] = []

    def want(name: str) -> bool:
        return not only or only in name

    journals = src.get("journals", [])
    for j in journals:
        if want(j["name"]) or want("journal"):
            it, st = collect_journal_toc(j, lookback_days=lb, today=today)
            items += it
            statuses.append(st)
    if want("ncpssd") or want("文献中心") or not only:
        it, st = collect_ncpssd(src.get("ncpssd", {}), journals, lookback_days=lb, today=today)
        items += it
        statuses.append(st)
    for ns in src.get("notice_sources", []):
        if want(ns["name"]) or want("notice"):
            it, st = collect_notice_source(ns, lookback_days=lb, drill_cfg=src.get("drilldown", {}), today=today)
            items += it
            statuses.append(st)
    if want("skygb") or want("数据库") or not only:
        it, st = collect_skygb(src.get("skygb", {}), today=today)
        items += it
        statuses.append(st)
    for feed in src.get("rss_feeds", []) or []:
        if want(feed.get("name", "")) or want("rss"):
            it, st = collect_rss(feed, lookback_days=lb, today=today)
            items += it
            statuses.append(st)

    lr = src.get("llm_research", {})
    client = make_client(settings.llm) if use_llm else None
    if client and lr.get("enabled", True) and (not only or only in ("llm", "LLM")):
        budget = int(lr.get("max_queries", 20))
        if lr.get("journals", True):
            it, st = collect_llm_journals(client, journals, year=today.year, budget=budget)
            items += it
            statuses.append(st)
            budget -= len(journals)
        if lr.get("projects", True) and budget > 0:
            it, st = collect_llm_projects(client, lr.get("project_queries", []), today=today, lookback_days=lb, budget=budget)
            items += it
            statuses.append(st)
    elif use_llm and not client:
        statuses.append(SourceStatus(name="LLM联网检索", ok=False, message="未配置 GEMINI_API_KEY / ANTHROPIC_API_KEY，已跳过", kind="llm"))
    return items, statuses


def filter_and_merge(items: list[Item], settings: Settings) -> list[Item]:
    clf = Classifier(settings.keywords)
    journal_names = {j["name"] for j in settings.sources.get("journals", [])}
    for j in settings.sources.get("journals", []):
        journal_names.update(j.get("aliases", []))
    merged: dict[str, Item] = {}
    for it in items:
        it.title = it.title.strip()
        if len(it.title) < 4:
            continue
        text = f"{it.title} {it.source} {it.extra.get('funder', '')} {it.extra.get('from_notice', '')} {it.extra.get('discipline', '')}"
        if it.kind == "project" and not clf.is_ethnology(text):
            continue
        if it.kind == "notice" and not clf.is_ethnology(text) and not any(k in it.title for k in ("立项", "名单", "公示", "重大", "专项")):
            continue
        clf.annotate(it)
        k = it.key()
        if k in merged:
            old = merged[k]
            # 合并：优先保留已核实/信息更全的版本
            keep, other = (old, it) if (old.verified, len(old.authors), len(old.affiliation)) >= (it.verified, len(it.authors), len(it.affiliation)) else (it, old)
            keep.url = keep.url or other.url
            keep.date = keep.date or other.date
            keep.authors = keep.authors or other.authors
            keep.affiliation = keep.affiliation or other.affiliation
            keep.verified = keep.verified or other.verified
            for u in other.evidence:
                if u not in keep.evidence:
                    keep.evidence.append(u)
            for kk, vv in other.extra.items():
                keep.extra.setdefault(kk, vv)
            merged[k] = keep
        else:
            merged[k] = it
    return list(merged.values())


def run(settings: Settings, *, today: date | None = None, use_llm: bool = True, send_email: bool = True,
        items_override: list[Item] | None = None, statuses_override: list[SourceStatus] | None = None,
        state_path: Path | None = None, report_dir: Path | None = None, only: str | None = None) -> dict[str, Any]:
    today = today or date.today()
    report_dir = report_dir or REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    period = period_label(today)
    slug = period_slug(today)

    if items_override is not None:
        raw, statuses = items_override, list(statuses_override or [])
    else:
        raw, statuses = collect_all(settings, today=today, use_llm=use_llm, only=only)
    items = filter_and_merge(raw, settings)

    state = State(state_path)
    new_items = [i for i in items if state.is_new(i)]
    log.info("collected %d items, %d new", len(items), len(new_items))

    client = make_client(settings.llm) if use_llm else None
    analysis_md, analysis_by = analyze(client, new_items, settings, today=today, period=period)

    notes: list[str] = []
    if not any(s.ok and s.count for s in statuses if s.kind in ("journal", "llm")):
        notes.append("本周期刊类数据源均未返回条目：请检查 config/sources.yaml 中的期刊目录页/文献中心接口，或配置 LLM 密钥启用联网检索兜底。")
    ctx = ReportContext(period=period, today=today, window_days=settings.lookback_days, new_items=new_items, all_items=items,
                        statuses=statuses, analysis_md=analysis_md, analysis_by=analysis_by, extra_notes=notes)
    md = render_markdown(ctx)
    html = to_html(md, f"民族学学科监测周报 {period}")
    md_path = report_dir / f"{slug}.md"
    html_path = report_dir / f"{slug}.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    (report_dir / "latest.md").write_text(md, encoding="utf-8")
    (report_dir / f"{slug}.items.json").write_text(json.dumps([i.to_dict() for i in new_items], ensure_ascii=False, indent=1), encoding="utf-8")

    mailed = False
    mail_error = ""
    if send_email:
        if settings.mail.available:
            try:
                subject = f"【民族学学科监测周报】{period}：新增论文{sum(1 for i in new_items if i.kind == 'paper')}篇 / 立项{sum(1 for i in new_items if i.kind == 'project')}项"
                send_mail(settings.mail, subject=subject, html=html, text=md,
                          attachments=[(f"民族学监测周报-{slug}.md", md.encode("utf-8"), "text/markdown")])
                mailed = True
            except Exception as exc:  # noqa: BLE001
                mail_error = str(exc)
                log.error("send mail failed: %s", exc)
        else:
            mail_error = "SMTP 未配置（需要 SMTP_HOST/SMTP_USER/SMTP_PASS）"
            log.warning(mail_error)

    state.mark(items, today)
    state.prune(today=today)
    state.record_run({"date": today.isoformat(), "period": period, "items": len(items), "new": len(new_items),
                      "mailed": mailed, "analysis_by": analysis_by,
                      "sources_ok": sum(1 for s in statuses if s.ok), "sources_total": len(statuses)})
    state.save()
    return {"period": period, "md": str(md_path), "html": str(html_path), "items": len(items), "new": len(new_items),
            "mailed": mailed, "mail_error": mail_error, "analysis_by": analysis_by,
            "statuses": [s.to_dict() for s in statuses]}


def load_demo_items() -> tuple[list[Item], list[SourceStatus]]:
    p = ROOT / "tests" / "fixtures" / "demo_items.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    items = [Item.from_dict(d) for d in data["items"]]
    statuses = [SourceStatus(**s) for s in data["statuses"]]
    return items, statuses
