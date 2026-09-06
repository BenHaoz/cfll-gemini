from ethno_monitor.pubs import Article, InstitutionMatcher, aggregate, article_key, issue_to_month, quarter_ranking, rank
from ethno_monitor.ranking import compute_ranking
import yaml


def test_issue_to_month_and_quarter():
    assert issue_to_month(3, "双月刊") == 5 and issue_to_month(4, "季刊") == 10 and issue_to_month(7, "月刊") == 7


def test_matcher_prefers_long_alias():
    m = InstitutionMatcher([{"name": "中央民族大学", "aliases": ["中央民大"]}, {"name": "西南民族大学", "aliases": []}])
    assert m.match("中央民族大学民族学与社会学学院") == "中央民族大学"
    assert m.match_all(["西南民族大学 民族学与社会学学院; 中央民大"]) == ["西南民族大学", "中央民族大学"]
    assert m.match("云南大学") == ""


def test_aggregate_and_rank():
    arts = [
        Article(key=article_key("民族研究", 2026, 3, "铸牢中华民族共同体意识研究"), title="铸牢中华民族共同体意识研究", journal="民族研究", year=2026, issue=3, institutions=["中央民族大学"]),
        Article(key=article_key("贵州民族研究", 2026, 3, "水族研究"), title="水族研究", journal="贵州民族研究", year=2026, issue=3, institutions=["中央民族大学", "广西民族大学"]),
        Article(key=article_key("贵州民族研究", 2023, 1, "旧文"), title="旧文", journal="贵州民族研究", year=2023, issue=1, institutions=["广西民族大学"]),
    ]
    meta = {"民族研究": {"frequency": "双月刊"}, "贵州民族研究": {"frequency": "双月刊"}}
    st = aggregate(arts, years=[2024, 2025, 2026], journal_meta=meta, top_tier_journals=["民族研究"])
    ranked = rank(st)
    assert ranked[0].name == "中央民族大学" and ranked[0].total == 2 and ranked[0].top_tier == 1 and ranked[0].community == 1
    assert st["广西民族大学"].total == 1
    assert quarter_ranking(st, "2026Q2") == [("中央民族大学", 2), ("广西民族大学", 1)]


def test_compute_ranking_handles_missing_indicators():
    cfg = yaml.safe_load(open("config/ranking.yaml", encoding="utf-8"))
    insts = [{"name": "A大学", "ethnology_phd": True, "community_phd": True, "bases": ["国家民委中华民族共同体研究基地"]},
             {"name": "B大学", "ethnology_phd": True, "community_phd": False, "bases": []}]
    from ethno_monitor.pubs import InstStats
    stats = {"A大学": InstStats(name="A大学", total=10, top_tier=2, community=4), "B大学": InstStats(name="B大学", total=5, top_tier=1, community=1)}
    rows, meta = compute_ranking(insts, stats, [], cfg, have_articles=True)
    assert rows[0].name == "A大学" and rows[0].total > rows[1].total
    assert meta["indicators_available"]["nsf_projects"] is False and "科研项目" not in meta["categories_used"]
    assert "senior_talents" in rows[0].missing


def test_split_organ():
    from ethno_monitor.harvest import split_organ
    assert split_organ("[1]中央民族大学民族学与社会学学院;[2]广西民族大学") == ["中央民族大学民族学与社会学学院", "广西民族大学"]
    assert split_organ("[1]不详") == []
