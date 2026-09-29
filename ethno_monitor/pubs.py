"""博士点单位发文统计：文章库（data/pubs/articles.jsonl）、单位匹配、三年/年度/季度聚合与排名。"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .config import DATA_DIR

PUBS_DIR = DATA_DIR / "pubs"
ARTICLES_PATH = PUBS_DIR / "articles.jsonl"

COMMUNITY_KW = ["中华民族共同体", "铸牢", "共同体意识", "民族团结进步", "交往交流交融", "三交", "互嵌", "共有精神家园", "五个认同", "中华民族现代文明"]
CORE_TIERS = ("CSSCI来源", "CSSCI扩展", "北大核心")
PLACEHOLDER_AFFS = (["(未解析)"], ["(接口无数据)"])

_FOOTNOTE = re.compile(r"\[[^\[\]]*\]|［[^［］]*］")


def clean_author_names(names: Iterable[str]) -> list[str]:
    """去掉作者名后的单位序号脚注，并修复按逗号误拆出的残片（'郝国强[1'、'2]' → '郝国强'）。"""
    merged: list[str] = []
    buf: str | None = None
    for tok in names or []:
        tok = str(tok)
        if buf is not None:
            buf += "," + tok
            if "]" in tok:
                merged.append(buf)
                buf = None
            continue
        if "[" in tok and "]" not in tok:
            buf = tok
        else:
            merged.append(tok)
    if buf is not None:
        merged.append(buf)
    out: list[str] = []
    for n in merged:
        n = re.sub(r"\[[^\]]*\]?|\([\d,，、\s]+\)", "", n).strip(" ,，;；")
        if n and not re.fullmatch(r"[\d,，、\s\]]+", n) and n not in out:
            out.append(n)
    return out


def split_author_field(raw: str) -> list[str]:
    """'郝国强[1,2];李星莹[1]' / '郝国强;包蕾' → ['郝国强', '李星莹']。"""
    raw = _FOOTNOTE.sub("", raw or "")
    return clean_author_names(x for x in re.split(r"[;；,，、]", raw) if x.strip())


@dataclass
class Article:
    key: str                      # 去重键（刊+年+期+标题 归一化）
    title: str
    journal: str
    year: int
    issue: int = 0
    date: str = ""                # YYYY-MM
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    institutions: list[str] = field(default_factory=list)   # 匹配到的标准单位名
    url: str = ""
    tier: str = ""                # CSSCI / CSSCI扩展 / 北大核心 / 其他
    source: str = "ncpssd"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PUNCT = re.compile(r"[\s　·•・,，.。;；:：!！?？\"“”'‘’()（）\[\]【】《》<>〈〉—\-–_/\\|]+")


def norm(s: str) -> str:
    return _PUNCT.sub("", s or "").lower()


def article_key(journal: str, year: int, issue: int, title: str) -> str:
    return f"{norm(journal)}|{year}|{issue}|{norm(title)[:80]}"


def issue_to_month(issue: int, frequency: str) -> int:
    """按刊期把期号折算为月份（月刊 n→n；双月刊 n→2n-1；季刊 n→3n-2）。"""
    f = (frequency or "").strip()
    if issue <= 0:
        return 0
    if f.startswith("月"):
        m = issue
    elif f.startswith("季"):
        m = 3 * issue - 2
    elif "半月" in f:
        m = (issue + 1) // 2
    else:  # 默认双月刊
        m = 2 * issue - 1
    return max(1, min(12, m))


def quarter_of(month: int) -> int:
    return (month - 1) // 3 + 1 if month else 0


# ---------------------------------------------------------------------------
# 单位匹配
# ---------------------------------------------------------------------------
class InstitutionMatcher:
    def __init__(self, institutions: list[dict[str, Any]]):
        self.insts = institutions
        self.patterns: list[tuple[str, str]] = []  # (alias, canonical)
        for inst in institutions:
            names = [inst["name"]] + list(inst.get("aliases") or [])
            for a in names:
                a = a.strip()
                if a:
                    self.patterns.append((a, inst["name"]))
        # 长别名优先，避免"民族大学"误配
        self.patterns.sort(key=lambda p: -len(p[0]))

    def match(self, affiliation: str) -> str:
        text = (affiliation or "").replace(" ", "")
        for alias, canon in self.patterns:
            if alias in text:
                return canon
        return ""

    def match_all(self, affiliations: Iterable[str]) -> list[str]:
        out: list[str] = []
        for aff in affiliations:
            for part in re.split(r"[;；,，、/]", aff or ""):
                c = self.match(part)
                if c and c not in out:
                    out.append(c)
        return out


# ---------------------------------------------------------------------------
# 文章库读写
# ---------------------------------------------------------------------------
def load_articles(path: Path | None = None) -> dict[str, Article]:
    path = path or ARTICLES_PATH
    out: dict[str, Article] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            allowed = {k: v for k, v in d.items() if k in Article.__dataclass_fields__}
            a = Article(**allowed)
            a.authors = clean_author_names(a.authors)
            out[a.key] = a
    return out


def save_articles(arts: dict[str, Article], path: Path | None = None) -> None:
    path = path or ARTICLES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for a in sorted(arts.values(), key=lambda x: (x.journal, x.year, x.issue, x.title)):
            f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")


def title_index_key(journal: str, title: str) -> str:
    return f"{norm(journal)}|{norm(title)[:60]}"


def _same_title_key(arts: dict[str, Article], idx: dict[str, list[str]], a: Article) -> str | None:
    """同刊同题且同一期，或一方尚无期号（网络首发）时视为同一篇；栏目导语等跨期同名条目不合并。"""
    for k in idx.get(title_index_key(a.journal, a.title), []):
        o = arts.get(k)
        if o and (not o.issue or not a.issue or (o.year, o.issue) == (a.year, a.issue)):
            return k
    return None


def upsert(arts: dict[str, Article], new: Iterable[Article]) -> int:
    """按去重键合并；键不同但属同一篇（网络首发稿后补正式期号、不同来源标点差异）也合并。"""
    idx: dict[str, list[str]] = defaultdict(list)
    for k, a in arts.items():
        idx[title_index_key(a.journal, a.title)].append(k)
    added = 0
    for a in new:
        tkey = title_index_key(a.journal, a.title)
        k = a.key if a.key in arts else _same_title_key(arts, idx, a)
        if k is None:
            arts[a.key] = a
            idx[tkey].append(a.key)
            added += 1
            continue
        old = arts[k]
        old.authors = old.authors or a.authors
        if a.affiliations and (not old.affiliations or old.affiliations in PLACEHOLDER_AFFS):
            old.affiliations = a.affiliations
            old.institutions = a.institutions or old.institutions
        old.institutions = old.institutions or a.institutions
        old.url = old.url or a.url
        old.date = old.date or a.date
        old.tier = old.tier or a.tier
        if not old.issue and a.issue and a.key not in arts:
            del arts[k]
            old.key, old.year, old.issue, old.date = a.key, a.year, a.issue, a.date or old.date
            arts[old.key] = old
            idx[tkey] = [old.key if x == k else x for x in idx[tkey]]
    return added


# ---------------------------------------------------------------------------
# 聚合与排名
# ---------------------------------------------------------------------------
@dataclass
class InstStats:
    name: str
    total: int = 0
    by_year: dict[int, int] = field(default_factory=dict)
    by_quarter: dict[str, int] = field(default_factory=dict)   # "2026Q1"
    community: int = 0                                          # 共同体主题论文
    top_tier: int = 0                                           # 顶级刊（民族研究/中华民族共同体研究/世界民族等）
    journals: Counter = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["journals"] = dict(self.journals.most_common(8))
        return d


def aggregate(arts: Iterable[Article], *, years: Iterable[int], journal_meta: dict[str, dict[str, Any]],
              top_tier_journals: Iterable[str]) -> dict[str, InstStats]:
    years = set(years)
    top = set(top_tier_journals)
    stats: dict[str, InstStats] = {}
    for a in arts:
        if a.year not in years or not a.institutions:
            continue
        freq = (journal_meta.get(a.journal) or {}).get("frequency", "双月刊")
        month = int(a.date[5:7]) if (a.date and len(a.date) >= 7) else issue_to_month(a.issue, freq)
        q = f"{a.year}Q{quarter_of(month)}" if month else f"{a.year}Q?"
        is_comm = any(k in a.title for k in COMMUNITY_KW)
        for inst in a.institutions:               # 多单位合作各计 1 篇（不做分数拆分，附注说明）
            s = stats.setdefault(inst, InstStats(name=inst))
            s.total += 1
            s.by_year[a.year] = s.by_year.get(a.year, 0) + 1
            s.by_quarter[q] = s.by_quarter.get(q, 0) + 1
            s.journals[a.journal] += 1
            if is_comm:
                s.community += 1
            if a.journal in top:
                s.top_tier += 1
    return stats


def rank(stats: dict[str, InstStats], key: str = "total") -> list[InstStats]:
    return sorted(stats.values(), key=lambda s: (-getattr(s, key), s.name))


def quarter_ranking(stats: dict[str, InstStats], quarter: str) -> list[tuple[str, int]]:
    rows = [(s.name, s.by_quarter.get(quarter, 0)) for s in stats.values()]
    return sorted([r for r in rows if r[1] > 0], key=lambda r: (-r[1], r[0]))


def latest_quarters(stats: dict[str, InstStats], n: int = 4) -> list[str]:
    qs = sorted({q for s in stats.values() for q in s.by_quarter if not q.endswith("?")})
    return qs[-n:]


def author_ranking(arts: Iterable[Article], institution: str, years: Iterable[int]) -> list[dict[str, Any]]:
    """某单位论文的作者发文排名。文献只给出论文层面的单位列表，故跨单位合作论文中的外单位合作者也会计入（cross 列标出）。"""
    years = set(years)
    rows: dict[str, dict[str, Any]] = {}
    for a in arts:
        if a.year not in years or institution not in a.institutions:
            continue
        cross = len(a.institutions) > 1
        names = clean_author_names(a.authors)
        for au in names:
            r = rows.setdefault(au, {"author": au, "total": 0, "first": 0, "cross": 0, "papers": []})
            r["total"] += 1
            r["first"] += int(names[0] == au)
            r["cross"] += int(cross)
            r["papers"].append(a)
    for r in rows.values():
        r["papers"].sort(key=lambda p: (-p.year, -p.issue))
    return sorted(rows.values(), key=lambda r: (-r["total"], -r["first"], r["author"]))


def coverage(arts: Iterable[Article], journal_meta: dict[str, dict[str, Any]], years: Iterable[int]) -> list[dict[str, Any]]:
    """各刊各年入库文章数与单位匹配率，用于报告附注。"""
    years = sorted(set(years))
    cnt: dict[str, Counter] = defaultdict(Counter)
    matched: dict[str, Counter] = defaultdict(Counter)
    for a in arts:
        if a.year in years:
            cnt[a.journal][a.year] += 1
            if a.institutions:
                matched[a.journal][a.year] += 1
    rows = []
    for j in journal_meta:
        rows.append({"journal": j, "tier": journal_meta[j].get("tier", ""), **{str(y): cnt[j][y] for y in years},
                     "matched": sum(matched[j].values()), "total": sum(cnt[j].values())})
    return rows
