from datetime import date
from pathlib import Path

from ethno_monitor.collectors.base import (date_from_url, extract_links, parse_date, parse_tables, rows_to_projects,
                                           find_attachments, soup_of, within_lookback)
from ethno_monitor.collectors.journals import parse_toc_generic
from ethno_monitor.llm.base import extract_json

FIX = Path(__file__).parent / "fixtures"


def test_parse_date_variants():
    assert parse_date("发布时间：2026年8月28日") == "2026-08-28"
    assert parse_date("2026-08-05 10:00") == "2026-08-05"
    assert parse_date("2026.8.5") == "2026-08-05"
    assert parse_date("2026年第4期 2026年8月") == "2026-08"
    assert parse_date("无日期") == ""


def test_date_from_url_patterns():
    assert date_from_url("http://www.nopss.gov.cn/n1/2026/0828/c431027-40801234.html", r"/n1/(\d{4})/(\d{2})(\d{2})/") == "2026-08-28"
    assert date_from_url("https://www.neac.gov.cn/seac/xxgk/202605/1190704.shtml", r"/(\d{4})(\d{2})/\d+\.shtml") == "2026-05"
    assert date_from_url("http://www.moe.gov.cn/srcsite/A13/s7061/202605/t20260520_1234.html", r"/t(\d{4})(\d{2})(\d{2})_") == "2026-05-20"


def test_within_lookback():
    today = date(2026, 9, 5)
    assert within_lookback("2026-08-28", 14, today)
    assert not within_lookback("2026-08-01", 14, today)
    assert within_lookback("2026-08", 14, today)          # 到月：8 月末在窗口内
    assert not within_lookback("2026-06", 14, today)
    assert within_lookback("", 14, today)                 # 无日期保留


def test_extract_people_list_links():
    html = (FIX / "people_list.html").read_text(encoding="utf-8")
    links = extract_links(soup_of(html), "http://www.nopss.gov.cn/GB/219469/431027/index.html", r"/n1/\d{4}/\d{4}/c\d+-\d+\.html")
    titles = [l["title"] for l in links]
    assert "2026年国家社科基金铸牢中华民族共同体意识研究专项立项名单公示" in titles
    assert all(l["url"].startswith("http://www.nopss.gov.cn/n1/") for l in links)
    assert len(links) == 4
    assert parse_date(links[0]["context"]) == "2026-08-28"


def test_table_rows_to_projects_with_header_and_filter():
    html = (FIX / "notice_table.html").read_text(encoding="utf-8")
    soup = soup_of(html)
    tables = parse_tables(soup)
    assert len(tables) == 1
    items = rows_to_projects(tables[0], source="社科办", funder="国家社科基金", url="http://x", keywords=["民族"], default_date="2026-08-20")
    assert [i.title for i in items] == ["南岭走廊多民族交往交流交融的历史经验研究", "中越跨境民族的国家认同建构研究"]
    assert items[0].extra["pi"] == "张三" and items[0].affiliation == "广西民族大学"
    assert items[1].extra["project_type"] == "青年项目"
    assert items[0].date == "2026-08-20"
    atts = find_attachments(soup, "http://www.nopss.gov.cn/n1/2026/0820/c431027-1.html")
    assert atts and atts[0]["url"].endswith("/NMediaFile/2026/0820/list.xlsx")


def test_table_rows_without_header_heuristic():
    rows = [["1", "壮族那文化的稻作景观与农业文化遗产活化研究", "李四", "广西民族大学", "一般项目"],
            ["2", "某无关课题名称研究", "王五", "某大学", "青年项目"]]
    items = rows_to_projects(rows, source="s", funder="国家民委民族研究项目", url="u", keywords=None)
    assert len(items) == 2
    assert items[0].extra["pi"] == "李四" and items[0].affiliation == "广西民族大学" and items[0].extra["project_type"] == "一般项目"


def test_parse_toc_generic():
    html = """<html><body><h2>2026年第4期目录</h2><ul>
    <li><a href="wkTextContent.aspx?colType=4&id=101">铸牢中华民族共同体意识的实践路径研究</a> <span>张三、李四</span> (1-12)</li>
    <li><a href="wkTextContent.aspx?colType=4&id=102">南岭走廊民族交往史论</a> <span>王五</span> (13-25)</li>
    <li><a href="index.aspx">返回首页</a></li></ul></body></html>"""
    items = parse_toc_generic(html, "http://gxmzyj.cbpt.cnki.net/WKE/WebPublication/wkTextContent.aspx?colType=4", "广西民族研究")
    assert [i.title for i in items] == ["铸牢中华民族共同体意识的实践路径研究", "南岭走廊民族交往史论"]
    assert items[0].authors == ["张三", "李四"]
    assert items[0].extra["issue"] == "2026年第4期" and items[0].date == "2026-07"
    assert items[0].url.startswith("http://gxmzyj.cbpt.cnki.net/WKE/WebPublication/wkTextContent.aspx?colType=4&id=101")


def test_extract_json_lenient():
    assert extract_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert extract_json('说明文字 [{"a": 1}, {"b": 2},] 结束') == [{"a": 1}, {"b": 2}]
    assert extract_json('{"x": [1,2]}') == {"x": [1, 2]}
    assert extract_json("没有 json") is None


def test_parse_toc_ncpssd():
    from ethno_monitor.collectors.journals import parse_toc_ncpssd
    html = """<html><body><header><a href="https://m.ncpssd.cn/index">国家哲学社会科学文献中心</a></header>
    <div class="info">世界民族 2026 / 3</div>
    <ul>
    <div class="catalog"><h2>2026年 第3期</h2>
    <p class="bg-r"><span class="title"><a href="javascript:void (0)" onclick="openDetail('/Literature/articleinfo?id=SJMZ2026003002&amp;type=journalArticle&amp;typename=中文期刊文章&amp;nav=1&amp;langType=1','中文期刊文章')" title="全球化变局下的民族共同体建设">全球化变局下的民族共同体建设</a></span>
    <tt><span class="title"><a data-id="SJMZ2026003002" data-type="中文期刊文章" onclick="AddHandleCount(this, '中文期刊文章', 'SJMZ2026003002', 1, -1, '/Literature/readurl?id=SJMZ2026003002', '96988A', '[C]', '全球化变局下的民族共同体建设', '张三[1];李四[2]', '世界民族')"></a></span></tt></p></div>
    <li><a href="javascript:void (0)">超越“一族一国”：北马其顿国家建构困境与再想象的可能性</a><span>王五</span></li>
    <li><a href="javascript:void (0)">更多</a></li>
    <li><a href="https://www.ncpssd.cn/topics/detailsList?id=4">建设中国特色新型智库</a></li>
    </ul></body></html>"""
    items = parse_toc_ncpssd(html, "https://m.ncpssd.cn/journal/details?gch=96988A", "世界民族")
    assert [i.title for i in items] == ["全球化变局下的民族共同体建设", "超越“一族一国”：北马其顿国家建构困境与再想象的可能性"]
    assert items[0].authors == ["张三", "李四"] and items[1].authors == ["王五"]
    assert items[0].extra["issue"] == "2026年第3期" and items[0].date == "2026-05"
    assert items[0].url == "https://www.ncpssd.cn/Literature/articleinfo?id=SJMZ2026003002&type=journalArticle&typename=中文期刊文章&nav=1&langType=1"
    assert items[0].extra["article_id"] == "SJMZ2026003002"
    assert items[1].url.startswith("https://m.ncpssd.cn/journal/details")


def test_nested_table_rows_and_header_detection():
    """社科基金数据库页面：外层表格嵌套分页行+数据表，表头不在首行也应正确映射。"""
    from ethno_monitor.collectors.base import parse_tables, rows_to_projects, soup_of
    html = """
    <table><tr><td>
      <table>
        <tr><td colspan="8">1 2 3 下一页</td></tr>
        <tr><td>项目批准号</td><td>项目类别</td><td>学科分类</td><td>项目名称</td><td>立项时间</td><td>项目负责人</td><td>专业职务</td><td>工作单位</td></tr>
        <tr><td>24XMZ092</td><td>西部项目</td><td>民族学</td><td>西方对新疆劳动力转移就业的负面叙事构建及应对研究</td><td>2024-01-01</td><td>张丽</td><td>教授</td><td>重庆邮电大学</td></tr>
        <tr><td>25WMZB005</td><td>中华学术外译项目</td><td>民族学</td><td>中国图腾文化</td><td>2025-12-23</td><td>倪丹</td><td>教授</td><td>西南大学</td></tr>
      </table>
    </td></tr></table>"""
    items = []
    for rows in parse_tables(soup_of(html)):
        items += rows_to_projects(rows, source="t", funder="国家社科基金", url="u", keywords=None)
    by_title = {i.title: i for i in items}
    assert "西方对新疆劳动力转移就业的负面叙事构建及应对研究" in by_title
    it = by_title["西方对新疆劳动力转移就业的负面叙事构建及应对研究"]
    assert it.extra["pi"] == "张丽" and it.affiliation == "重庆邮电大学"
    assert it.extra["project_type"] == "西部项目" and it.extra["discipline"] == "民族学" and it.extra["project_no"] == "24XMZ092"
    assert it.date.startswith("2024-01")
    # 外层表格的巨型单元格不应被当作条目
    assert all(len(t) < 80 for t in by_title)


def test_skygb_next_page_href():
    from ethno_monitor.collectors.base import soup_of
    from ethno_monitor.collectors.skygb import next_page_href
    soup = soup_of('<div><a href="//bp.people.com.cn/skygb/sk/index.php/index/seach/2?xktype=a&lxtime=2025">2</a>'
                   '<a href="//bp.people.com.cn/skygb/sk/index.php/index/seach/2?xktype=a&lxtime=2025">下一页</a></div>')
    assert next_page_href(soup, "http://fz.people.com.cn/skygb/sk/index.php/Index/seach") == \
        "http://bp.people.com.cn/skygb/sk/index.php/index/seach/2?xktype=a&lxtime=2025"
    assert next_page_href(soup_of("<p>无</p>"), "http://x/") == ""
