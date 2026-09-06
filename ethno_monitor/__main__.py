"""命令行入口：python -m ethno_monitor <run|demo|collect|test-email>"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from .config import load_settings
from pathlib import Path

from .pipeline import collect_all, dump_collected, filter_and_merge, load_demo_items, load_items_file, run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ethno_monitor", description="民族学学科监测系统")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="完整运行：采集、分析、生成周报并发送邮件")
    p_run.add_argument("--no-email", action="store_true", help="不发送邮件")
    p_run.add_argument("--no-llm", action="store_true", help="不调用 LLM（规则兜底）")
    p_run.add_argument("--date", help="指定运行日期 YYYY-MM-DD（默认今天）")
    p_run.add_argument("--only", help="只运行名称包含该字符串的数据源")
    p_run.add_argument("--items-file", help="补充条目 JSON（如 Claude 会话联网检索结果），与采集结果合并")
    p_run.add_argument("--analysis-file", help="外部撰写的分析 Markdown，替代 LLM/规则分析")
    p_run.add_argument("--analysis-label", default="Claude 会话分析", help="分析引擎标签")
    p_run.add_argument("--no-site", action="store_true", help="不重建 docs/ 观察站网页")
    p_run.add_argument("--collected-file", help="使用 collect --out 生成的采集结果，替代现场采集")

    p_demo = sub.add_parser("demo", help="使用示例数据演示完整流程（不联网抓取）")
    p_demo.add_argument("--email", action="store_true", help="演示时也发送邮件")
    p_demo.add_argument("--llm", action="store_true", help="演示时调用 LLM 做分析")

    p_col = sub.add_parser("collect", help="只采集并打印条目（调试数据源）")
    p_col.add_argument("--only", help="只运行名称包含该字符串的数据源")
    p_col.add_argument("--llm", action="store_true")
    p_col.add_argument("--out", help="把采集结果（条目 + 数据源状态）写入 JSON 文件")
    p_col.add_argument("--diagnose", action="store_true", help="打印各数据源页面结构诊断（用于远程校正选择器）")

    p_prompt = sub.add_parser("prompt", help="输出分析提示词（含本周新增条目摘要与广西知识库），供外部分析器使用")
    p_prompt.add_argument("--items-file", action="append", default=[], help="条目 JSON，可多次指定")
    p_prompt.add_argument("--date", help="运行日期 YYYY-MM-DD")
    p_prompt.add_argument("--all", action="store_true", help="不按 state 过滤，把全部条目视为新增")

    sub.add_parser("site", help="仅根据 reports/ 重建 docs/ 观察站网页")

    p_h = sub.add_parser("harvest", help="抓取核心期刊近三年文章（文献中心），补作者单位，写入 data/pubs/articles.jsonl")
    p_h.add_argument("--years", type=int, default=3)
    p_h.add_argument("--max-issues", type=int, default=60, help="本次最多抓取的期页数")
    p_h.add_argument("--max-details", type=int, default=300, help="本次最多抓取的详情页数")
    p_h.add_argument("--journal", help="只抓名称包含该字符串的期刊")
    p_h.add_argument("--sleep", type=float, default=0.6)
    p_h.add_argument("--projects", action="store_true", help="同时抓取国家社科基金项目数据库近三年民族问题研究立项")

    sub.add_parser("stats", help="根据文章库输出博士点单位发文排名、学科指数（Markdown）")

    sub.add_parser("test-email", help="发送一封测试邮件验证 SMTP 配置")

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()

    if a.cmd == "run":
        today = date.fromisoformat(a.date) if a.date else None
        extra = load_items_file(Path(a.items_file)) if a.items_file else None
        analysis = Path(a.analysis_file).read_text(encoding="utf-8") if a.analysis_file else None
        items_ov = statuses_ov = None
        if a.collected_file:
            from .models import SourceStatus
            data = json.loads(Path(a.collected_file).read_text(encoding="utf-8"))
            items_ov = load_items_file(Path(a.collected_file))
            statuses_ov = [SourceStatus(**{k: v for k, v in st.items() if k in SourceStatus.__dataclass_fields__}) for st in data.get("statuses", [])]
        res = run(settings, today=today, use_llm=not a.no_llm, send_email=not a.no_email, only=a.only,
                  items_override=items_ov, statuses_override=statuses_ov,
                  extra_items=extra, analysis_override=analysis, analysis_label=a.analysis_label, build_site=not a.no_site)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "prompt":
        from .analysis import build_prompt
        from .report import period_label
        from .state import State
        today = date.fromisoformat(a.date) if a.date else date.today()
        raw = []
        for f in a.items_file:
            raw += load_items_file(Path(f))
        items = filter_and_merge(raw, settings)
        if not a.all:
            st = State()
            items = [i for i in items if st.is_new(i)]
        print(build_prompt(items, settings, today=today, period=period_label(today)))
        return 0
    if a.cmd == "harvest":
        from .harvest import harvest
        res = harvest(years_back=a.years, max_issue_pages=a.max_issues, max_detail_pages=a.max_details, sleep_s=a.sleep, journals_filter=a.journal)
        for row in res.pop("log", []):
            print(row)
        print(json.dumps(res, ensure_ascii=False))
        if a.projects:
            from .harvest import harvest_projects
            print(json.dumps(harvest_projects(years_back=a.years), ensure_ascii=False))
        return 0
    if a.cmd == "stats":
        from .sections import build_extra_sections
        print(build_extra_sections(date.today()))
        return 0
    if a.cmd == "site":
        from .config import DOCS_DIR, REPORT_DIR
        from .report import render_site
        print(render_site(REPORT_DIR, DOCS_DIR, settings))
        return 0
    if a.cmd == "demo":
        items, statuses = load_demo_items()
        from .config import DATA_DIR, REPORT_DIR
        res = run(settings, use_llm=a.llm, send_email=a.email, items_override=items, statuses_override=statuses,
                  state_path=DATA_DIR / "state.demo.json", report_dir=REPORT_DIR / "demo", docs_dir=REPORT_DIR / "demo" / "site")
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "collect":
        items, statuses = collect_all(settings, today=date.today(), use_llm=a.llm, only=a.only)
        if a.out:
            dump_collected(items, statuses, Path(a.out))
        for s in statuses:
            print(("OK " if s.ok else "ERR"), s.name, s.count, s.message)
        for it in items:
            print(f"[{it.kind}] {it.date} {it.source} | {it.title} | {'、'.join(it.authors)} | {it.url}")
        if a.diagnose:
            from .diagnose import diagnose
            print(diagnose(settings))
        return 0
    if a.cmd == "test-email":
        from .mailer import send_mail
        if not settings.mail.available:
            print("SMTP 未配置：需要 SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / MAIL_TO", file=sys.stderr)
            return 2
        send_mail(settings.mail, subject="【民族学学科监测系统】测试邮件", html="<p>SMTP 配置成功，周报将按计划发送。</p>", text="SMTP 配置成功。")
        print("测试邮件已发送至", settings.mail.to)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
