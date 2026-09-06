"""仿软科方法的中华民族共同体学学科指数：指标归一化 + 加权汇总，附数据覆盖说明。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .pubs import InstStats


@dataclass
class RankRow:
    name: str
    total: float = 0.0
    categories: dict[str, float] = field(default_factory=dict)      # 类别得分（0-100）
    raw: dict[str, float] = field(default_factory=dict)             # 指标原始值
    missing: list[str] = field(default_factory=list)                # 缺数据的指标


def _raw_indicators(inst: dict[str, Any], stats: InstStats | None, projects: list[dict[str, Any]]) -> dict[str, float | None]:
    name = inst["name"]
    bases = inst.get("bases") or []
    nat = [b for b in bases if any(k in b for k in ("国家民委", "教育部", "四部委", "中央统战部", "国家级"))]
    own_projects = [p for p in projects if name in (p.get("institutions") or [])]
    major = [p for p in own_projects if any(k in (p.get("type") or "") + (p.get("funder") or "") for k in ("重大", "专项"))]
    talents = inst.get("talents")
    return {
        "ethnology_phd": 1.0 if inst.get("ethnology_phd") else 0.0,
        "community_phd": 1.0 if inst.get("community_phd") else 0.0,
        "national_bases": float(len(nat)),
        "other_bases": float(len(bases) - len(nat) + len(inst.get("other_bases") or [])),
        "nsf_projects": float(len(own_projects)) if projects else None,
        "major_projects": float(len(major)) if projects else None,
        "core_papers": float(stats.total) if stats else (0.0 if stats is not None else None),
        "top_papers": float(stats.top_tier) if stats else None,
        "community_papers": float(stats.community) if stats else None,
        "senior_talents": float(len(talents)) if isinstance(talents, list) else None,
    }


def compute_ranking(institutions: list[dict[str, Any]], stats: dict[str, InstStats], projects: list[dict[str, Any]],
                    cfg: dict[str, Any], *, have_articles: bool) -> tuple[list[RankRow], dict[str, Any]]:
    cats: dict[str, Any] = cfg.get("categories", {})
    raws: dict[str, dict[str, float | None]] = {}
    for inst in institutions:
        st = stats.get(inst["name"])
        if have_articles and st is None:
            st = InstStats(name=inst["name"])
        raws[inst["name"]] = _raw_indicators(inst, st, projects)
    # 指标可用性：至少一个单位有非空值且不全为 0
    indicator_ok: dict[str, bool] = {}
    for cat in cats.values():
        for ind in cat["indicators"]:
            vals = [r[ind] for r in raws.values() if r.get(ind) is not None]
            indicator_ok[ind] = bool(vals) and max(vals) > 0
    maxes = {ind: max((r[ind] or 0.0) for r in raws.values()) for ind in indicator_ok if indicator_ok[ind]}

    rows: list[RankRow] = []
    for inst in institutions:
        r = raws[inst["name"]]
        row = RankRow(name=inst["name"], raw={k: (v if v is not None else float("nan")) for k, v in r.items()})
        total_w = 0.0
        total = 0.0
        for cname, cat in cats.items():
            cw = float(cat.get("weight", 0))
            iw_sum = 0.0
            cscore = 0.0
            for ind, spec in cat["indicators"].items():
                if not indicator_ok.get(ind):
                    row.missing.append(ind)
                    continue
                iw = float(spec.get("weight", 1))
                v = r.get(ind) or 0.0
                cscore += iw * (100.0 * v / maxes[ind] if maxes[ind] else 0.0)
                iw_sum += iw
            if iw_sum > 0:
                cscore /= iw_sum
                row.categories[cname] = round(cscore, 1)
                total += cw * cscore
                total_w += cw
            else:
                row.categories[cname] = float("nan")
        row.total = round(total / total_w, 1) if total_w else 0.0
        rows.append(row)
    rows.sort(key=lambda x: (-x.total, x.name))
    meta = {"indicators_available": {k: v for k, v in indicator_ok.items()},
            "categories_used": [c for c in cats if any(indicator_ok.get(i) for i in cats[c]["indicators"])],
            "weights": {c: cats[c]["weight"] for c in cats}}
    return rows, meta
