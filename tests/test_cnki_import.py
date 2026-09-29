from pathlib import Path

from ethno_monitor.cnki_import import import_records, parse_cnki_file
from ethno_monitor.collectors.journals import _authors_from_handle
from ethno_monitor.collectors.base import soup_of
from ethno_monitor.pubs import Article, InstitutionMatcher, article_key, author_ranking, clean_author_names, split_author_field

CORE = [
    {"name": "广西民族研究", "tier": "CSSCI来源", "frequency": "双月刊"},
    {"name": "中南民族大学学报（人文社会科学版）", "tier": "CSSCI来源", "frequency": "月刊"},
    {"name": "青海民族大学学报（社会科学版）", "tier": "待核实", "frequency": "季刊"},
    {"name": "西北民族研究", "tier": "CSSCI扩展", "frequency": "双月刊"},
]
MATCHER = InstitutionMatcher([{"name": "广西民族大学"}, {"name": "中央民族大学"}])

REFWORKS = """RT Journal Article
SR 1
A1 郝国强;包蕾
AD 广西民族大学民族学与社会学学院;
T1 从“猺”到“瑶”：基于《大瑶山团结公约》的中华民族共同体意识“三重再造”机制研究
JF 广西民族研究
YR 2026
IS 01
OP 1-12
LK https://link.cnki.net/example1
DS CNKI

RT Journal Article
A1 宋天琢;郝国强
AD 广西民族大学;
T1 新时代党的民族理论政策法律化的核心内涵、运行机制、本质特征与时代价值
JF 中南民族大学学报(人文社会科学版)
YR 2026
DS CNKI

RT Journal Article
A1 郝国强
AD 广西民族大学;
T1 共生型现代化：中国式现代化的在地逻辑与理论探索
JF 湖北大学学报(哲学社会科学版)
YR 2026
IS 02
"""

ENDNOTE = """%0 Journal Article
%A 郝国强
%A 黄惠群
%+ 广西民族大学民族学与社会学学院;
%T 何以共生：南岭走廊多民族龙文化的集体叙事与边缘创新
%J 广西民族研究
%D 2025
%N 03
%W CNKI
"""


def test_clean_author_names_repairs_split_footnotes():
    assert clean_author_names(["郝国强[1", "2]", "李星莹"]) == ["郝国强", "李星莹"]
    assert clean_author_names(["蒙思丞[1", "2]", "苏建健[3", "2]"]) == ["蒙思丞", "苏建健"]
    assert clean_author_names(["张三", "张三", "李四"]) == ["张三", "李四"]
    assert split_author_field("郝国强[1,2];李星莹[1]") == ["郝国强", "李星莹"]
    assert split_author_field("郝国强;包蕾;") == ["郝国强", "包蕾"]


def test_authors_from_handle_keeps_multi_affiliation_names():
    html = ("<li><a onclick=\"AddHandleCount(this, '中文期刊文章', 'X1', 1, -1, '/r', '96988A', '[C]', '题名', "
            "'郝国强[1,2];李星莹[1]', '湖北民族大学学报')\"></a></li>")
    assert _authors_from_handle(soup_of(html).find("li")) == ["郝国强", "李星莹"]


def test_parse_refworks_and_endnote(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text(REFWORKS, encoding="utf-8")
    recs = parse_cnki_file(f)
    assert len(recs) == 3
    assert recs[0]["authors"] == ["郝国强", "包蕾"] and recs[0]["organs"] == ["广西民族大学民族学与社会学学院"]
    assert recs[0]["year"] == 2026 and recs[0]["issue"] == 1 and recs[1]["issue"] == 0
    g = tmp_path / "b.txt"
    g.write_text(ENDNOTE, encoding="gb18030")
    r = parse_cnki_file(g)
    assert r[0]["authors"] == ["郝国强", "黄惠群"] and r[0]["journal"] == "广西民族研究" and r[0]["issue"] == 3


def test_parse_html_and_xlsx_tables(tmp_path: Path):
    header = ["SrcDatabase-来源库", "Title-题名", "Author-作者", "Organ-单位", "Source-文献来源", "PubTime-发表时间", "Year-年", "Period-期"]
    row = ["期刊", "以史为鉴，赓续文脉", "郝国强;", "广西民族大学;", "广西民族研究", "2025-10-20", "2025", "05"]
    html = "<table><tr>" + "".join(f"<td>{h}</td>" for h in header) + "</tr><tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr></table>"
    f = tmp_path / "export.xls"
    f.write_text(html, encoding="utf-8")
    rec = parse_cnki_file(f)[0]
    assert rec["journal"] == "广西民族研究" and rec["date"] == "2025-10" and rec["issue"] == 5 and rec["authors"] == ["郝国强"]
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(header)
    wb.active.append(row)
    x = tmp_path / "export.xlsx"
    wb.save(x)
    assert parse_cnki_file(x)[0]["title"] == "以史为鉴，赓续文脉"


def test_import_filters_journals_and_merges(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text(REFWORKS, encoding="utf-8")
    title = "双向互构与南北交融——七仙女传说演变中的中华民族共同体意识生成机制"
    existing = Article(key=article_key("西北民族研究", 2025, 3, title), title=title, journal="西北民族研究", year=2025, issue=3,
                       authors=["郝国强", "诸葛成影"], affiliations=["(未解析)"])
    arts = {existing.key: existing}
    recs = parse_cnki_file(f) + [{"title": title.replace("——", "—"), "authors": ["郝国强"], "organs": ["广西民族大学"],
                                  "journal": "西北民族研究", "year": 2025, "issue": 3, "date": "", "url": ""},
                                 {"title": "正增长社会", "authors": ["郝国强"], "organs": ["广西民族大学"],
                                  "journal": "青海民族大学学报(社会科学版)", "year": 2025, "issue": 3, "date": "", "url": ""}]
    res = import_records(recs, arts, CORE, MATCHER)
    assert res["added"] == 2 and res["merged"] == 1
    assert any("湖北大学学报" in k for k in res["skipped"]) and any("待核实" in k for k in res["skipped"])
    assert existing.affiliations == ["广西民族大学"] and existing.institutions == ["广西民族大学"]
    online_first = next(a for a in arts.values() if a.journal.startswith("中南民族大学学报"))
    assert online_first.issue == 0 and online_first.source == "cnki"
    # 网络首发稿后来有了正式期号：并入原条目而不是重复计数
    later = dict(recs[1], issue=9, date="2026-09")
    import_records([later], arts, CORE, MATCHER)
    zn = [a for a in arts.values() if a.journal.startswith("中南民族大学学报")]
    assert len(zn) == 1 and zn[0].issue == 9 and zn[0].key in arts
    ranking = author_ranking(arts.values(), "广西民族大学", [2025, 2026])
    assert ranking[0]["author"] == "郝国强" and ranking[0]["total"] == 3


def test_same_column_title_in_different_issues_is_not_merged():
    from ethno_monitor.pubs import upsert
    t = "民族团结进步促进法专题研究"
    a1 = Article(key=article_key("贵州民族研究", 2026, 2, t), title=t, journal="贵州民族研究", year=2026, issue=2)
    arts = {a1.key: a1}
    a2 = Article(key=article_key("贵州民族研究", 2026, 4, t), title=t, journal="贵州民族研究", year=2026, issue=4)
    assert upsert(arts, [a2]) == 1 and len(arts) == 2
