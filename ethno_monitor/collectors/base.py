"""采集器公共工具：日期解析、链接抽取、表格解析、附件解析。"""
from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..models import Item

log = logging.getLogger(__name__)

CJK = re.compile(r"[一-鿿]")
DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})"),
    re.compile(r"(20\d{2})[-/.年](\d{1,2})月?"),
]
NAME_RE = re.compile(r"^[一-鿿·]{2,4}$")
UNIT_RE = re.compile(r"(大学|学院|研究院|研究所|研究中心|党校|社会科学院|社科院|科学院|干部学院|学会|博物馆|出版社|编辑部|委员会)")


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_date(text: str) -> str:
    """从任意文本中抽取第一个日期，返回 ISO 字符串（可能只有到月）。"""
    if not text:
        return ""
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            g = m.groups()
            try:
                if len(g) == 3:
                    return date(int(g[0]), int(g[1]), int(g[2])).isoformat()
                return f"{int(g[0]):04d}-{int(g[1]):02d}"
            except ValueError:
                continue
    return ""


def date_from_url(url: str, regex: str) -> str:
    if not regex:
        return ""
    m = re.search(regex, url)
    if not m:
        return ""
    g = [x for x in m.groups() if x]
    try:
        if len(g) >= 3:
            return date(int(g[0]), int(g[1]), int(g[2])).isoformat()
        if len(g) == 2:
            return f"{int(g[0]):04d}-{int(g[1]):02d}"
        if len(g) == 1 and len(g[0]) == 8:
            return datetime.strptime(g[0], "%Y%m%d").date().isoformat()
        if len(g) == 1 and len(g[0]) == 6:
            return f"{g[0][:4]}-{g[0][4:]}"
    except ValueError:
        return ""
    return ""


def within_lookback(date_str: str, lookback_days: int, today: date | None = None) -> bool:
    """无法解析日期 -> 保留（交给 state 去重）；仅到月 -> 该月末仍在窗口内即保留。"""
    if not date_str:
        return True
    today = today or date.today()
    cutoff = today - timedelta(days=lookback_days)
    try:
        if len(date_str) == 7:
            y, m = int(date_str[:4]), int(date_str[5:7])
            end = (date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1))
            return end >= cutoff
        if len(date_str) == 4:
            return int(date_str) >= cutoff.year
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date() >= cutoff
    except ValueError:
        return True


def has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(k and k in text for k in keywords)


def extract_links(soup: BeautifulSoup, base_url: str, link_regex: str = "",
                  min_title_len: int = 6) -> list[dict[str, str]]:
    """抽取列表页链接：标题、绝对 URL、所在列表项文本（用于取日期）。"""
    pat = re.compile(link_regex) if link_regex else None
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        abs_url = urljoin(base_url, href)
        title = clean(a.get("title") or a.get_text(" "))
        if len(title) < min_title_len or not CJK.search(title):
            continue
        if pat and not pat.search(abs_url):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        parent = a.parent
        ctx = ""
        for _ in range(3):
            if parent is None or not isinstance(parent, Tag):
                break
            ctx = clean(parent.get_text(" "))
            if parse_date(ctx):
                break
            parent = parent.parent
        out.append({"title": title, "url": abs_url, "context": ctx})
    return out


def parse_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for t in soup.find_all("table"):
        rows: list[list[str]] = []
        for tr in t.find_all("tr"):
            # 只取直接子单元格，避免嵌套表格的内容并入外层行
            cells = [clean(td.get_text(" ")) for td in tr.find_all(["td", "th"], recursive=False)]
            if any(cells):
                rows.append(cells)
        if len(rows) >= 2:
            tables.append(rows)
    return tables


HEADER_MAP = {
    "title": ["项目名称", "课题名称", "项目题目", "课题题目", "题目", "名称", "选题"],
    "pi": ["项目负责人", "负责人", "首席专家", "申请人", "主持人", "姓名"],
    "unit": ["工作单位", "所在单位", "责任单位", "依托单位", "单位", "学校", "申报单位", "推荐单位"],
    "ptype": ["项目类别", "课题类别", "类别", "项目类型", "类型"],
    "discipline": ["学科分类", "学科", "所属学科", "学科门类"],
    "date": ["立项时间", "批准时间", "立项日期", "年度", "立项年度"],
    "no": ["批准号", "项目编号", "项目批准号", "课题编号", "编号"],
}


def _map_header(header: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for field, names in HEADER_MAP.items():
        for i, h in enumerate(header):
            if any(n == h or (n in h and len(h) <= len(n) + 4) for n in names):
                if field not in idx:
                    idx[field] = i
                break
    return idx


def rows_to_projects(rows: list[list[str]], *, source: str, funder: str, url: str,
                     keywords: Iterable[str] | None, default_date: str = "",
                     ptype_hint: str = "") -> list[Item]:
    """表格行 -> 课题条目。有表头则按表头映射，否则用启发式。"""
    if not rows:
        return []
    # 表头可能不在首行（前面有分页/标题行）：在前 3 行内寻找可映射的表头
    idx: dict[str, int] = {}
    body = rows
    for hi, header in enumerate(rows[:3]):
        cand = _map_header(header)
        if "title" in cand and len(cand) >= 2:
            idx, body = cand, rows[hi + 1:]
            break
    kws = list(keywords or [])
    items: list[Item] = []
    for r in body:
        if not any(r):
            continue
        title = pi = unit = ptype = disc = d = no = ""
        if "title" in idx and idx["title"] < len(r):
            title = r[idx["title"]]
            pi = r[idx["pi"]] if "pi" in idx and idx["pi"] < len(r) else ""
            unit = r[idx["unit"]] if "unit" in idx and idx["unit"] < len(r) else ""
            ptype = r[idx["ptype"]] if "ptype" in idx and idx["ptype"] < len(r) else ""
            disc = r[idx["discipline"]] if "discipline" in idx and idx["discipline"] < len(r) else ""
            d = parse_date(r[idx["date"]]) if "date" in idx and idx["date"] < len(r) else ""
            no = r[idx["no"]] if "no" in idx and idx["no"] < len(r) else ""
        else:
            cands = [c for c in r if len(c) >= 8 and CJK.search(c) and not UNIT_RE.search(c)]
            if not cands:
                continue
            title = max(cands, key=len)
            for c in r:
                if c == title:
                    continue
                if NAME_RE.match(c) and not pi and not re.search(r"项目|课题|民族学|研究", c):
                    pi = c
                elif UNIT_RE.search(c) and not unit:
                    unit = c
                elif re.search(r"(重点|一般|青年|重大|西部|专项|自筹|后期|冷门)", c) and len(c) <= 12 and not ptype:
                    ptype = c
        title = clean(title)
        if len(title) < 6 or title in ("项目名称", "课题名称"):
            continue
        row_text = " ".join(r) + " " + funder
        if kws and not has_any(row_text, kws):
            continue
        items.append(Item(
            kind="project", title=title, url=url, source=source, date=d or default_date,
            authors=[pi] if pi else [], affiliation=unit,
            extra={"funder": funder, "project_type": ptype or ptype_hint, "discipline": disc, "project_no": no, "pi": pi},
        ))
    return items


def find_attachments(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower().split("?")[0]
        if low.endswith((".xlsx", ".xls", ".docx", ".doc", ".pdf", ".zip", ".rar")):
            out.append({"title": clean(a.get_text(" ")) or href.rsplit("/", 1)[-1], "url": urljoin(base_url, href)})
    return out


def parse_xlsx(content: bytes) -> list[list[list[str]]]:
    try:
        import openpyxl  # noqa: WPS433
    except ImportError:  # pragma: no cover
        return []
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("xlsx parse failed: %s", exc)
        return []
    tables = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [clean(str(c)) if c is not None else "" for c in row]
            if any(cells):
                rows.append(cells)
        if len(rows) >= 2:
            # 跳过标题行（只有一个非空单元格）直到出现表头
            while rows and sum(1 for c in rows[0] if c) <= 1 and len(rows) > 2:
                rows.pop(0)
            tables.append(rows)
    return tables
