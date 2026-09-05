"""命令行入口：python -m ethno_monitor <run|demo|collect|test-email>"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from .config import load_settings
from .pipeline import collect_all, load_demo_items, run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ethno_monitor", description="民族学学科监测系统")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="完整运行：采集、分析、生成周报并发送邮件")
    p_run.add_argument("--no-email", action="store_true", help="不发送邮件")
    p_run.add_argument("--no-llm", action="store_true", help="不调用 LLM（规则兜底）")
    p_run.add_argument("--date", help="指定运行日期 YYYY-MM-DD（默认今天）")
    p_run.add_argument("--only", help="只运行名称包含该字符串的数据源")

    p_demo = sub.add_parser("demo", help="使用示例数据演示完整流程（不联网抓取）")
    p_demo.add_argument("--email", action="store_true", help="演示时也发送邮件")
    p_demo.add_argument("--llm", action="store_true", help="演示时调用 LLM 做分析")

    p_col = sub.add_parser("collect", help="只采集并打印条目（调试数据源）")
    p_col.add_argument("--only", help="只运行名称包含该字符串的数据源")
    p_col.add_argument("--llm", action="store_true")

    sub.add_parser("test-email", help="发送一封测试邮件验证 SMTP 配置")

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()

    if a.cmd == "run":
        today = date.fromisoformat(a.date) if a.date else None
        res = run(settings, today=today, use_llm=not a.no_llm, send_email=not a.no_email, only=a.only)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "demo":
        items, statuses = load_demo_items()
        from .config import DATA_DIR, REPORT_DIR
        res = run(settings, use_llm=a.llm, send_email=a.email, items_override=items, statuses_override=statuses,
                  state_path=DATA_DIR / "state.demo.json", report_dir=REPORT_DIR / "demo")
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "collect":
        items, statuses = collect_all(settings, today=date.today(), use_llm=a.llm, only=a.only)
        for s in statuses:
            print(("OK " if s.ok else "ERR"), s.name, s.count, s.message)
        for it in items:
            print(f"[{it.kind}] {it.date} {it.source} | {it.title} | {'、'.join(it.authors)} | {it.url}")
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
