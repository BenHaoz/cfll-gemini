"""扩展板块：博士点单位发文排名、主要学者最新观点、仿软科学科指数（供周报与网页复用）。"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import CONFIG_DIR, DATA_DIR
from .pubs import ARTICLES_PATH, PUBS_DIR, aggregate, coverage, latest_quarters, load_articles, quarter_ranking, rank
from .ranking import compute_ranking

SCHOLARS_LATEST = PUBS_DIR / "scholars_latest.json"
PROJECTS_PATH = PUBS_DIR / "projects.jsonl"


def load_yaml(name: str) -> dict[str, Any]:
    p = CONFIG_DIR / name
    return yaml.safe_load(open(p, encoding="utf-8")) or {} if p.exists() else {}


def load_projects() -> list[dict[str, Any]]:
    if not PROJECTS_PATH.exists():
        return []
    out = []
    for line in open(PROJECTS_PATH, encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _fmt(v: float) -> str:
    return "—" if (v is None or (isinstance(v, float) and math.isnan(v))) else (f"{v:.1f}" if isinstance(v, float) else str(v))


def build_pubs_section(today: date, *, top_n: int = 30) -> tuple[str, dict[str, Any]]:
    insts_cfg = load_yaml("institutions.yaml")
    core = load_yaml("journals_core.yaml")
    rank_cfg = load_yaml("ranking.yaml")
    institutions = insts_cfg.get("institutions", [])
    journal_meta = {j["name"]: j for j in core.get("journals", [])}
    years = list(range(today.year - int(rank_cfg.get("window_years", 3)) + 1, today.year + 1))
    arts = load_articles()
    if not arts or not institutions:
        return ("### 六、博士点单位发文排名\n\n文章库尚未建立或单位名录缺失，本板块待下次采集后生成。\n", {"stats": {}, "years": years})
    stats = aggregate(arts.values(), years=years, journal_meta=journal_meta, top_tier_journals=rank_cfg.get("top_tier_journals", []))
    # 只保留博士点单位
    names = {i["name"] for i in institutions}
    stats = {k: v for k, v in stats.items() if k in names}
    for i in institutions:
        stats.setdefault(i["name"], type(next(iter(stats.values())))(name=i["name"])) if stats else None
    ranked = rank(stats)
    qs = latest_quarters(stats, 4)
    L: list[str] = []
    L.append("### 六、博士点单位发文排名（北核/南核民族学类期刊）")
    L.append("")
    L.append(f"统计口径：{years[0]}—{years[-1]} 年，`config/journals_core.yaml` 中等级为 CSSCI 来源/扩展或北大核心的民族学类期刊；按作者单位匹配到博士点单位（含所属院系），多单位合作各计 1 篇；文章库共 {len(arts)} 篇，其中匹配到博士点单位 {sum(1 for a in arts.values() if a.institutions)} 篇。")
    # 作者单位解析进度（按年）：元数据自最新一期起回填，早年份未完成时该年计数偏低
    prog = []
    for y in years:
        tot = sum(1 for a in arts.values() if a.year == y)
        done_n = sum(1 for a in arts.values() if a.year == y and a.affiliations and a.affiliations not in (["(未解析)"], ["(接口无数据)"]))
        prog.append(f"{y} 年 {done_n}/{tot}（{(100 * done_n // tot) if tot else 0}%）")
    L.append(f"作者单位解析进度：{'；'.join(prog)}。解析自最新一期起逐周回填，解析率低的年份计数偏低，排名以解析完成年份为准。")
    L.append("")
    head = "| 排名 | 单位 | 近三年合计 | " + " | ".join(str(y) for y in years) + " | 共同体主题 | 顶级刊 | 主要发文期刊 |"
    L.append(head)
    L.append("|" + "---|" * (head.count("|") - 1))
    for i, s in enumerate(ranked[:top_n], 1):
        if s.total == 0:
            continue
        top_j = "、".join(f"{j}({n})" for j, n in s.journals.most_common(3))
        L.append(f"| {i} | {s.name} | {s.total} | " + " | ".join(str(s.by_year.get(y, 0)) for y in years) + f" | {s.community} | {s.top_tier} | {top_j} |")
    L.append("")
    if qs:
        L.append("**季度发文排名（最近四个季度）**")
        L.append("")
        L.append("| 季度 | 排名前十（单位·篇数） |")
        L.append("|---|---|")
        for q in reversed(qs):
            top = quarter_ranking(stats, q)[:10]
            L.append(f"| {q} | " + "；".join(f"{n} {c}" for n, c in top) + " |")
        L.append("")
    cov = coverage(arts.values(), journal_meta, years)
    covered = [c for c in cov if c["total"] > 0]
    missing = [c["journal"] for c in cov if c["total"] == 0]
    L.append(f"> 覆盖说明：已入库 {len(covered)} 种期刊；未入库 {len(missing)} 种（{('、'.join(missing[:12]) + ('…' if len(missing) > 12 else '')) if missing else '无'}）。作者单位来自文献中心详情页，匹配率见附录。")
    L.append("")
    return "\n".join(L), {"stats": stats, "years": years, "ranked": ranked}


def build_scholars_section(today: date) -> str:
    insts_cfg = load_yaml("institutions.yaml")
    scholars = insts_cfg.get("scholars", [])
    latest: list[dict[str, Any]] = []
    if SCHOLARS_LATEST.exists():
        try:
            latest = json.loads(SCHOLARS_LATEST.read_text(encoding="utf-8")).get("items", [])
        except json.JSONDecodeError:
            latest = []
    L = ["### 七、博士点单位主要学者最新观点", ""]
    if not scholars:
        L.append("学者名录尚未建立（config/institutions.yaml → scholars）。")
        return "\n".join(L)
    # 文章库中学者近期论文（作者名精确匹配，近两年）
    arts = load_articles()
    names = {s["name"]: s for s in scholars}
    papers: list[tuple[str, Any]] = []
    for a in arts.values():
        if a.year >= today.year - 1:
            for au in a.authors:
                if au in names:
                    papers.append((au, a))
    papers.sort(key=lambda x: (-x[1].year, -x[1].issue))
    L.append(f"名录共 {len(scholars)} 位学者（来自 config/institutions.yaml）。本期：文章库中匹配到学者论文 {len(papers)} 篇（近两年，按作者名精确匹配，同名风险请留意）；联网检索到有链接可核的最新观点/动态 {len(latest)} 条（由 Claude 会话整理）。")
    L.append("")
    if papers:
        L.append("**学者近期论文（文章库匹配）**")
        L.append("")
        L.append("| 学者 | 单位 | 论文 | 期刊 / 期号 | 链接 |")
        L.append("|---|---|---|---|---|")
        for au, a in papers[:40]:
            link = f"[链接]({a.url})" if a.url else ""
            L.append(f"| {au} | {names[au].get('institution','')} | {a.title} | {a.journal} {a.year}年第{a.issue}期 | {link} |")
        L.append("")
    if latest:
        L.append("**学者最新观点与动态（联网检索）**")
        L.append("")
        L.append("| 学者 | 单位 | 最新观点 / 成果 | 日期 | 来源 |")
        L.append("|---|---|---|---|---|")
        for it in sorted(latest, key=lambda x: x.get("date", ""), reverse=True):
            link = f"[链接]({it['url']})" if it.get("url") else ""
            L.append(f"| {it.get('name','')} | {it.get('institution','')} | {it.get('viewpoint','')} | {it.get('date','')} | {link} |")
        L.append("")
    by_inst: dict[str, list[str]] = {}
    for s in scholars:
        by_inst.setdefault(s.get("institution", ""), []).append(f"{s['name']}（{s.get('title','')}）" if s.get("title") else s["name"])
    L.append("<details><summary>学者名录（按单位）</summary>")
    L.append("")
    for inst, names in by_inst.items():
        L.append(f"- **{inst}**：{'、'.join(names)}")
    L.append("")
    L.append("</details>")
    L.append("")
    return "\n".join(L)


def build_ranking_section(today: date, pubs_meta: dict[str, Any]) -> str:
    insts_cfg = load_yaml("institutions.yaml")
    rank_cfg = load_yaml("ranking.yaml")
    institutions = insts_cfg.get("institutions", [])
    L = ["### 八、中华民族共同体学学科指数（仿软科方法·自建）", ""]
    if not institutions:
        L.append("单位名录尚未建立。")
        return "\n".join(L)
    stats = pubs_meta.get("stats") or {}
    rows, meta = compute_ranking(institutions, stats, load_projects(), rank_cfg, have_articles=bool(stats))
    cats = list(rank_cfg.get("categories", {}).keys())
    L.append("方法：参照软科“中国最好学科排名”的指标体系，设人才培养、平台基地、科研项目、学术论文、高端人才五类指标，各指标按参评单位最大值归一化为 0–100 分后加权汇总；权重与指标定义见 `config/ranking.yaml`，可自行调整。"
             f"本期可用类别：{'、'.join(meta['categories_used'])}；数据缺失的指标不计分并在下表以“—”标示。")
    L.append("")
    L.append("| 排名 | 单位 | 综合得分 | " + " | ".join(f"{c}({rank_cfg['categories'][c]['weight']})" for c in cats) + " | 民族学博士点 | 共同体学博士点 |")
    L.append("|" + "---|" * (len(cats) + 5))
    inst_map = {i["name"]: i for i in institutions}
    for i, r in enumerate(rows, 1):
        inst = inst_map.get(r.name, {})
        L.append(f"| {i} | {r.name} | {r.total:.1f} | " + " | ".join(_fmt(r.categories.get(c, float('nan'))) for c in cats)
                 + f" | {'✔' if inst.get('ethnology_phd') is True else ('?' if inst.get('ethnology_phd') == 'unknown' else '—')} | {'✔' if inst.get('community_phd') is True else ('?' if inst.get('community_phd') == 'unknown' else '—')} |")
    L.append("")
    missing_inds = [k for k, v in meta["indicators_available"].items() if not v]
    if missing_inds:
        L.append(f"> “?”表示博士点信息未能核实（按无计分）。暂缺数据的指标：{'、'.join(missing_inds)}。指标口径与来源标注见 `config/ranking.yaml`；单位属性（博士点、基地、人才）来自 `config/institutions.yaml`，均附来源链接，欢迎校正。")
        L.append("")
    return "\n".join(L)


def _item_row(it: Any) -> str:
    au = "、".join(it.authors[:3]) if it.authors else ""
    link = f"[链接]({it.url})" if it.url else ""
    flag = "" if it.verified else " ⚠未核实"
    return f"| {it.title}{flag} | {au} | {it.source} {it.extra.get('issue', '') or it.date} | {(it.extra.get('summary') or '')[:80]} | {link} |"


def build_theme_sections(new_items: list[Any], today: date) -> str:
    """九、各民族共同现代化专题；十、国外民族学人类学理论前沿。输入为本周新增条目（含专题标签）。"""
    mod = [i for i in new_items if "各民族共同现代化" in (i.extra.get("themes") or [])]
    theory = [i for i in new_items if "国外理论前沿" in (i.extra.get("themes") or [])]
    L: list[str] = []
    L.append("### 九、各民族共同现代化专题（顶刊·985 高校·国外研究）")
    L.append("")
    L.append("口径：本周新增条目中命中“共同现代化/民族地区现代化/共同富裕”等专题词者（中文），或国外文献中同时含现代化/发展与民族/族群/土著语境者；另含专题期刊（中国社会科学、社会学研究、历史研究及 985 高校学报）目录中命中专题词的文章。中国式现代化研究院与 985 高校成果动态由每周会话联网检索补充（见分析部分）。")
    L.append("")
    cn = [i for i in mod if str(i.extra.get("lang", "zh")) == "zh"]
    en = [i for i in mod if str(i.extra.get("lang", "zh")) != "zh"]
    if not mod:
        L.append("本周未监测到专题相关新增条目。")
        L.append("")
    if cn:
        L.append(f"**国内（{len(cn)} 篇）**")
        L.append("")
        L.append("| 题目 | 作者 | 来源 / 期号 | 摘要 | 链接 |")
        L.append("|---|---|---|---|---|")
        for i in sorted(cn, key=lambda x: (x.source, x.date)):
            L.append(_item_row(i))
        L.append("")
    if en:
        L.append(f"**国外（{len(en)} 篇）**")
        L.append("")
        L.append("| Title | Authors | Journal / Date | Abstract | Link |")
        L.append("|---|---|---|---|---|")
        for i in sorted(en, key=lambda x: (x.source, x.date)):
            L.append(_item_row(i))
        L.append("")
    L.append("### 十、国外民族学人类学理论前沿动态")
    L.append("")
    L.append("口径：American Anthropologist、Current Anthropology、HAU、Anthropological Theory、Annual Review of Anthropology、JRAI 等理论类期刊 RSS 的最新文章，以及族群/民族主义与中国研究类期刊中命中理论词的文章；按期刊分组，理论要点由每周会话在分析部分归纳。")
    L.append("")
    if not theory:
        L.append("本周未获取到国外理论类期刊的新增文章（请查看数据源状态中的 RSS 条目）。")
    else:
        by_src: dict[str, list[Any]] = {}
        for i in theory:
            by_src.setdefault(i.source, []).append(i)
        for src_name, lst in sorted(by_src.items(), key=lambda kv: -len(kv[1])):
            L.append(f"**{src_name}**（{len(lst)}）")
            L.append("")
            for i in lst[:12]:
                au = "、".join(i.authors[:3])
                L.append(f"- [{i.title}]({i.url}) {('— ' + au) if au else ''}{(' · ' + i.date) if i.date else ''}")
            if len(lst) > 12:
                L.append(f"- …另 {len(lst) - 12} 篇略")
            L.append("")
    return "\n".join(L)


def build_extra_sections(today: date, new_items: list[Any] | None = None) -> str:
    pubs_md, meta = build_pubs_section(today)
    parts = [pubs_md, build_scholars_section(today), build_ranking_section(today, meta)]
    parts.append(build_theme_sections(new_items or [], today))
    return "\n".join(parts)
