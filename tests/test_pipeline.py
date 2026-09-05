import json
from datetime import date
from pathlib import Path

from ethno_monitor.classify import Classifier
from ethno_monitor.config import load_settings
from ethno_monitor.models import Item
from ethno_monitor.pipeline import filter_and_merge, load_demo_items, run
from ethno_monitor.report import period_label, period_slug, to_html
from ethno_monitor.state import State


def test_classifier_directions():
    s = load_settings()
    clf = Classifier(s.keywords)
    assert clf.classify_text("铸牢中华民族共同体意识的历史逻辑") == "中华民族共同体学"
    assert clf.classify_text("民族区域自治制度的法治保障") == "马克思主义民族理论与政策"
    assert clf.classify_text("中越边境跨境婚姻的民族志研究") == "人类学与世界民族"
    assert clf.classify_text("瑶族过山榜文献中的迁徙记忆") == "中华民族学"
    assert clf.classify_text("完全无关的题目") == "中华民族学"
    assert clf.is_guangxi("南岭走廊瑶族研究") and not clf.is_guangxi("藏彝走廊研究")


def test_filter_and_merge_dedup_and_ethnology_filter():
    s = load_settings()
    a = Item(kind="paper", title="铸牢中华民族共同体意识研究", source="民族研究", verified=False, evidence=["http://e1"])
    b = Item(kind="paper", title="铸牢中华民族共同体意识研究。", source="民族研究", authors=["张三"], url="http://x")
    c = Item(kind="project", title="数字经济与区域协调发展研究", source="s", extra={"funder": "国家社科基金"})
    d = Item(kind="project", title="某课题研究", source="s", extra={"funder": "国家民委民族研究项目"})
    out = filter_and_merge([a, b, c, d], s)
    titles = {i.title for i in out}
    assert "数字经济与区域协调发展研究" not in titles      # 非民族学课题被过滤
    assert "某课题研究" in titles                          # 国家民委课题：资助方即民族类
    merged = [i for i in out if i.kind == "paper"][0]
    assert merged.verified and merged.authors == ["张三"] and "http://e1" in merged.evidence
    assert merged.direction == "中华民族共同体学"


def test_state_new_detection(tmp_path: Path):
    st = State(tmp_path / "state.json")
    it = Item(kind="paper", title="测试题目", source="s")
    assert st.is_new(it)
    st.mark([it], date(2026, 9, 5))
    st.save()
    st2 = State(tmp_path / "state.json")
    assert not st2.is_new(it)
    st2.prune(keep_days=1, today=date(2027, 1, 1))
    assert st2.is_new(it)


def test_period_labels():
    assert period_label(date(2026, 9, 5)) == "2026年第36周"
    assert period_slug(date(2026, 9, 5)) == "2026-W36"


def test_run_demo_end_to_end(tmp_path: Path):
    s = load_settings()
    items, statuses = load_demo_items()
    res = run(s, today=date(2026, 9, 5), use_llm=False, send_email=False, items_override=items,
              statuses_override=statuses, state_path=tmp_path / "state.json", report_dir=tmp_path / "reports", docs_dir=tmp_path / "site")
    assert res["new"] == 12 and res["mailed"] is False and res["site"].endswith("index.html")
    md = Path(res["md"]).read_text(encoding="utf-8")
    assert "民族学学科监测周报 · 2026年第36周" in md
    assert "四、研究分析与广西特色选题策划" in md and "| 序号 | 论文/课题题目 |" in md
    assert "⚠未核实" in md and "🌿桂" in md
    html = Path(res["html"]).read_text(encoding="utf-8")
    assert "<table>" in html and "示例" in html
    # 第二次运行：全部条目已见，新增为 0
    res2 = run(s, today=date(2026, 9, 12), use_llm=False, send_email=False, items_override=items,
               statuses_override=statuses, state_path=tmp_path / "state.json", report_dir=tmp_path / "reports", docs_dir=tmp_path / "site")
    assert res2["new"] == 0
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert len(st["runs"]) == 2


def test_to_html_tables():
    html = to_html("| a | b |\n|---|---|\n| 1 | 2 |", "t")
    assert "<td>1</td>" in html


def test_settings_tolerate_empty_env(monkeypatch):
    monkeypatch.setenv("LOOKBACK_DAYS", "")
    monkeypatch.setenv("SMTP_PORT", "")
    monkeypatch.setenv("LLM_TIMEOUT", "")
    s = load_settings()
    assert s.lookback_days == 14 and s.mail.port == 465 and s.llm.timeout == 180


def test_guangxi_flag_ignores_journal_name():
    s = load_settings()
    clf = Classifier(s.keywords)
    a = clf.annotate(Item(kind="paper", title="珠三角乡村都市化研究", source="广西民族研究"))
    b = clf.annotate(Item(kind="paper", title="京族哈节的海洋文化基因", source="民族研究"))
    assert a.guangxi_related is False and b.guangxi_related is True
