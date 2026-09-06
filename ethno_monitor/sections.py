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
    L.append(f"名录共 {len(scholars)} 位学者（来自 config/institutions.yaml），本周检索到 {len(latest)} 条最新观点。观点摘要由 Claude 会话依据来源网页整理，仅收录有链接可核的内容。")
    L.append("")
    if latest:
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
    L.append("方法：参照软科"中国最好学科排名"的指标体系，设人才培养、平台基地、科研项目、学术论文、高端人才五类指标，各指标按参评单位最大值归一化为 0–100 分后加权汇总；权重与指标定义见 `config/ranking.yaml`，可自行调整。"
             f"本期可用类别：{'、'.join(meta['categories_used'])}；数据缺失的指标不计分并在下表以"—"标示。")
    L.append("")
    L.append("| 排名 | 单位 | 综合得分 | " + " | ".join(f"{c}({rank_cfg['categories'][c]['weight']})" for c in cats) + " | 民族学博士点 | 共同体学博士点 |")
    L.append("|" + "---|" * (len(cats) + 5))
    inst_map = {i["name"]: i for i in institutions}
    for i, r in enumerate(rows, 1):
        inst = inst_map.get(r.name, {})
        L.append(f"| {i} | {r.name} | {r.total:.1f} | " + " | ".join(_fmt(r.categories.get(c, float('nan'))) for c in cats)
                 + f" | {'✔' if inst.get('ethnology_phd') else '—'} | {'✔' if inst.get('community_phd') else '—'} |")
    L.append("")
    missing_inds = [k for k, v in meta["indicators_available"].items() if not v]
    if missing_inds:
        L.append(f"> 暂缺数据的指标：{'、'.join(missing_inds)}。指标口径与来源标注见 `config/ranking.yaml`；单位属性（博士点、基地、人才）来自 `config/institutions.yaml`，均附来源链接，欢迎校正。")
        L.append("")
    return "\n".join(L)


def build_extra_sections(today: date) -> str:
    pubs_md, meta = build_pubs_section(today)
    return "\n".join([pubs_md, build_scholars_section(today), build_ranking_section(today, meta)])
