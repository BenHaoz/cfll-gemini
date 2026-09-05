"""研究趋势分析与广西特色选题策划（LLM 生成，无密钥时规则兜底）。"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date
from typing import Any

import yaml

from .classify import Classifier
from .config import DIRECTIONS, Settings
from .llm import LLMClient
from .models import Item

log = logging.getLogger(__name__)

SYSTEM = """你是一位资深民族学学科带头人兼科研管理专家，长期在广西从事民族研究，熟悉《民族研究》《中华民族共同体研究》《广西民族研究》等 C 刊的选题偏好，以及国家社科基金、国家民委民族研究项目、教育部重大课题攻关项目的申报规律。
写作要求：使用规范学术中文；论断要有本周监测数据支撑（引用具体论文/课题题目时用《》标注），不得编造监测数据之外的论文、课题或人名；选题必须具体、可操作、有明确的理论切口与经验材料，并说明与广西区域特色的结合点。"""

ANALYSIS_PROMPT = """今天是 {today}，本期为第 {period} 期周报。以下是本周民族学学科监测到的新增论文、课题立项与公告（已按四个方向初步分类；"[未核实]"表示仅由联网检索得到、缺少来源链接）。

=== 四个学科方向 ===
{directions}

=== 本周监测数据 ===
{digest}

=== 广西区域知识库（选题策划时结合使用）===
{guangxi}

请输出 Markdown（不要输出一级标题，使用 ### 作为节标题），依次包含以下六节：

### 一、本周学术动态总评
300 字左右：本周论文与立项的总体态势、最突出的主题、值得注意的信号。

### 二、四个方向分述
对每个方向：① 本周热点主题与代表性成果（引用题目）；② 理论与方法动向；③ 对广西学者的启示。每个方向 150–250 字；若某方向本周无新增，请明确说明并给出一句判断。

### 三、课题立项态势与申报启示
分析本周立项/公告反映的资助导向（资助机构偏好、高频关键词、区域分布），给出 3–5 条面向下一申报周期的具体建议（含可申报的项目类别与时间提示）。

### 四、广西特色选题策划
结合本周动态与广西知识库（南岭走廊、十二个世居民族、中越跨境民族与东南亚民族研究、平陆运河与面向东盟开放、民族团结进步示范区等），提出 12 个具体选题。用 Markdown 表格输出，列为：序号 | 论文/课题题目 | 所属方向 | 选题依据（关联本周哪些成果或立项） | 广西切入点与经验材料 | 拟投期刊 / 可申报项目类别。
四个方向各至少 2 个；题目应达到可直接用于投稿或申报的成熟度（主副标题结构，避免空泛）。

### 五、重点论文/课题精读建议
从本周条目中挑选 5 条最值得精读或对标的论文/课题，各用 1–2 句话说明理由。

### 六、下周关注建议
3–5 条：即将到来的申报节点、会议、专刊征稿或值得跟踪的主题。"""


def directions_text(settings: Settings) -> str:
    lines = []
    for d in DIRECTIONS:
        desc = ((settings.keywords.get("directions") or {}).get(d) or {}).get("description", "")
        lines.append(f"- {d}：{desc}")
    return "\n".join(lines)


def build_digest(items: list[Item], *, max_papers: int = 150, max_projects: int = 100, max_notices: int = 40) -> str:
    papers = [i for i in items if i.kind == "paper"]
    projects = [i for i in items if i.kind == "project"]
    notices = [i for i in items if i.kind == "notice"]
    out: list[str] = []

    def tag(i: Item) -> str:
        return "" if i.verified else "[未核实]"

    out.append(f"【新增论文 {len(papers)} 篇】")
    by_dir: dict[str, list[Item]] = defaultdict(list)
    for p in papers[:max_papers]:
        by_dir[p.direction].append(p)
    for d in DIRECTIONS:
        if by_dir.get(d):
            out.append(f"-- {d}（{len(by_dir[d])}）")
            for p in by_dir[d]:
                au = "、".join(p.authors[:3])
                issue = p.extra.get("issue") or p.date
                gx = "[桂]" if p.guangxi_related else ""
                out.append(f"  * {tag(p)}{gx}《{p.title}》 {au} —《{p.source}》{issue}")
    out.append(f"\n【新增课题立项 {len(projects)} 项】")
    by_f: dict[str, list[Item]] = defaultdict(list)
    for p in projects[:max_projects]:
        by_f[p.extra.get("funder") or p.source].append(p)
    for f, lst in by_f.items():
        out.append(f"-- {f}（{len(lst)}）")
        for p in lst:
            pi = p.extra.get("pi") or (p.authors[0] if p.authors else "")
            t = p.extra.get("project_type", "")
            gx = "[桂]" if p.guangxi_related else ""
            out.append(f"  * {tag(p)}{gx}[{p.direction}]《{p.title}》 {pi} {p.affiliation} {t} {p.date}")
    out.append(f"\n【相关公告 {len(notices)} 条】")
    for n in notices[:max_notices]:
        out.append(f"  * {tag(n)}{n.date} {n.source}：{n.title}")
    return "\n".join(out)


def guangxi_text(settings: Settings) -> str:
    region = settings.guangxi.get("region", {})
    return yaml.safe_dump(region, allow_unicode=True, sort_keys=False, width=200)[:6000]


def analyze(client: LLMClient | None, items: list[Item], settings: Settings, *, today: date, period: str) -> tuple[str, str]:
    """返回 (分析 Markdown, 生成方式)。"""
    if client is not None:
        try:
            prompt = ANALYSIS_PROMPT.format(today=today.isoformat(), period=period, directions=directions_text(settings),
                                            digest=build_digest(items), guangxi=guangxi_text(settings))
            text = client.generate(prompt, system=SYSTEM, max_tokens=12000).strip()
            if len(text) > 400:
                return text, f"LLM（{client.name}）"
            log.warning("LLM 输出过短，退化为规则分析")
        except Exception as exc:  # noqa: BLE001
            log.error("LLM 分析失败: %s", exc)
    return fallback_analysis(items, settings, today=today), "规则兜底（未配置或调用失败 LLM）"


def _hot_keywords(items: list[Item], clf: Classifier, top: int = 12) -> list[tuple[str, int]]:
    cnt: Counter[str] = Counter()
    for it in items:
        text = it.title
        for rules in clf.rules.values():
            for kw, _w in rules:
                if len(kw) >= 2 and kw in text:
                    cnt[kw] += 1
    return cnt.most_common(top)


def fallback_analysis(items: list[Item], settings: Settings, *, today: date) -> str:
    clf = Classifier(settings.keywords)
    papers = [i for i in items if i.kind == "paper"]
    projects = [i for i in items if i.kind == "project"]
    notices = [i for i in items if i.kind == "notice"]
    by_dir: dict[str, list[Item]] = defaultdict(list)
    for i in papers + projects:
        by_dir[i.direction].append(i)
    hot = _hot_keywords(papers + projects, clf)
    gx = [i for i in papers + projects if i.guangxi_related]
    out: list[str] = []
    out.append("### 一、本周学术动态总评")
    out.append(f"本周共监测到新增论文 {len(papers)} 篇、课题立项 {len(projects)} 项、相关公告 {len(notices)} 条。"
               + (f"高频主题词：{'、'.join(f'{k}({v})' for k, v in hot[:8])}。" if hot else "")
               + (f"其中与广西直接相关的成果/课题 {len(gx)} 项。" if gx else "本周暂无直接涉桂成果，建议关注区域性议题的比较研究空间。")
               + "（本节为规则自动生成；配置 GEMINI_API_KEY 或 ANTHROPIC_API_KEY 后可获得深度分析。）")
    out.append("\n### 二、四个方向分述")
    for d in DIRECTIONS:
        lst = by_dir.get(d, [])
        out.append(f"\n**{d}**（{len(lst)} 条）")
        if not lst:
            out.append("- 本周无新增条目。")
        for i in lst[:5]:
            who = "、".join(i.authors[:2]) or i.extra.get("pi", "")
            out.append(f"- 《{i.title}》{('—' + who) if who else ''}（{i.source}{'，' + i.date if i.date else ''}）")
    out.append("\n### 三、课题立项态势与申报启示")
    funders = Counter((p.extra.get("funder") or p.source) for p in projects)
    if funders:
        out.append("本周立项按资助机构分布：" + "；".join(f"{k} {v} 项" for k, v in funders.most_common()) + "。")
    out.append("- 建议持续对照全国社科办、国家民委官网公告，关注铸牢中华民族共同体意识研究专项与国家民委民族研究项目的年度申报节点。")
    out.append("- 关注教育部哲学社会科学研究重大课题攻关项目招标选题中涉及边疆治理、民族地区现代化与中华文明标识的方向。")
    out.append("\n### 四、广西特色选题策划")
    out.append("| 序号 | 论文/课题题目 | 所属方向 | 选题依据 | 广西切入点 | 拟投期刊 / 项目类别 |")
    out.append("|---|---|---|---|---|---|")
    bank = settings.guangxi.get("topic_bank", {})
    week = today.isocalendar()[1]
    n = 0
    for d in DIRECTIONS:
        pool = bank.get(d, [])
        if not pool:
            continue
        for k in range(3):
            t = pool[(week + k) % len(pool)]
            n += 1
            basis = "结合本周" + d + "方向动态" if by_dir.get(d) else "该方向本周较冷，属前瞻性布局"
            out.append(f"| {n} | {t['title']} | {d} | {basis} | 广西田野与地方文献 | {t.get('venue', '')} |")
    out.append("\n### 五、重点论文/课题精读建议")
    picks = sorted(papers + projects, key=lambda i: (not i.guangxi_related, not i.verified))[:5]
    if picks:
        for i in picks:
            out.append(f"- 《{i.title}》（{i.source}）：{'涉桂成果，可直接对标；' if i.guangxi_related else ''}属{i.direction}方向。")
    else:
        out.append("- 本周无新增条目可供精读。")
    out.append("\n### 六、下周关注建议")
    out.append("- 跟踪全国哲学社会科学工作办公室“通知公告/年度项目/重大项目”栏目新公示。")
    out.append("- 跟踪国家民委政府信息公开栏目关于民族研究项目立项、结项及研究基地的通知。")
    out.append("- 关注各民族学期刊最新一期上线情况及专题征稿。")
    return "\n".join(out)
