# 民族学学科监测系统使用说明

面向民族学学科四个方向 —— **马克思主义民族理论与政策、中华民族学、人类学与世界民族、中华民族共同体学** —— 的自动监测与周报系统：

1. **论文监测**：民族研究、中华民族共同体研究、中央民族大学学报、西北民族研究、广西民族研究、贵州民族研究、青海民族大学学报、广西民族大学学报、世界民族、青海民族研究等民族学类 C 刊的最新文章；
2. **课题立项监测**：国家社科基金（年度项目、重大项目、铸牢中华民族共同体意识研究专项、后期资助等）、国家民委民族研究项目、教育部哲学社会科学研究重大课题攻关项目等；
3. **每周研究分析报告**：四方向趋势分述、立项态势与申报启示、**结合广西区域特色（南岭走廊、十二个世居民族、中越跨境民族与东南亚民族研究、平陆运河与面向东盟开放等）的选题与论文题目策划**；
4. **每周一自动推送到 Gmail（aa1928@gmail.com）**，同时把报告归档到仓库 `reports/`，并更新观察站网页（Claude Artifact 页面 https://claude.ai/code/artifact/4deee0c5-bc00-4d00-9aec-c5511a4786fc ；`docs/index.html` 亦可一键开启 GitHub Pages：仓库 Settings → Pages → Source 选 `main` 分支 `/docs` 目录，地址为 https://benhaoz.github.io/cfll-gemini/ ）。

## 零、当前运行方式（无需你配置任何密钥）

1. **每周一 06:30（北京时间）** GitHub Actions 工作流「民族学监测·每周采集」（`.github/workflows/weekly-collect.yml`，无需密钥）在境外运行器上抓取各期刊与立项来源，把条目与数据源状态提交到 `data/collected/latest.json`，并在日志中输出页面结构诊断。
2. **每周一 08:30（北京时间）** Claude Code 的 **Routine** 自动开启一个会话，按 [`docs/WEEKLY_RUNBOOK.md`](WEEKLY_RUNBOOK.md) 执行：读取采集结果 → 用联网检索补充 → 由 Claude 撰写六节分析与广西特色选题 → 生成周报与观察站网页并提交到 `main` → 重新发布观察站 Artifact → 通过已连接的 Gmail 发送到 aa1928@gmail.com。
下文的 GitHub Actions 方案是**备用路径**（需自行配置 SMTP / LLM 密钥，仅手动触发）。

示例报告见 [`docs/sample-report.md`](sample-report.md)（示例数据，非真实文献）。

---

## 一、系统架构

```
GitHub Actions（每周一 08:30 北京时间）
   │
   ├─ 采集层（config/sources.yaml 配置驱动，逐源尽力而为，失败不阻断）
   │    ├─ 期刊：期刊官网/CNKI 腾云目录页 · 国家哲学社会科学文献中心 · RSS
   │    ├─ 课题：全国社科办（年度/重大/通知公告）· 国家民委 · 教育部社科司 · sinoss
   │    │        └─ 立项公告自动"下钻"：解析正文表格与 xlsx 附件，抽取民族学相关课题
   │    ├─ 国家社科基金项目数据库（按学科"民族学"检索）
   │    └─ LLM 联网检索兜底（Gemini google_search / Claude web_search）：逐刊查最新目录、查最新立项公告
   │
   ├─ 处理层：四方向关键词分类 · 民族学相关性过滤 · 涉桂标注 · 跨源去重 · 与 data/state.json 比对判定"本周新增"
   ├─ 分析层：LLM 生成趋势分析 + 广西特色选题（12 个可直接投稿/申报的题目）；无密钥时规则兜底
   └─ 输出层：Markdown + HTML 周报 → SMTP 邮件 → 归档提交回仓库
```

## 二、备用部署（GitHub Actions，需自行配置密钥）

### 1. 配置仓库 Secrets（Settings → Secrets and variables → Actions → *Secrets*）

| 名称 | 必填 | 说明 |
|---|---|---|
| `SMTP_HOST` | ✅ | 发件服务器，如 `smtp.qq.com`（推荐用你自己的 QQ 邮箱发给自己，最不易被拦截） |
| `SMTP_PORT` | ✅ | `465`（SSL，推荐）或 `587`（STARTTLS） |
| `SMTP_USER` | ✅ | 发件邮箱账号，如 `38064358@qq.com` |
| `SMTP_PASS` | ✅ | **SMTP 授权码**（QQ 邮箱：设置 → 账号 → POP3/SMTP 服务 → 开启并生成授权码；不是登录密码） |
| `MAIL_FROM` | 可选 | 发件人地址，默认同 `SMTP_USER` |
| `GEMINI_API_KEY` | 推荐 | Gemini API 密钥，启用联网检索兜底与深度分析 |
| `ANTHROPIC_API_KEY` | 可选 | 若改用 Claude，填写此项并把变量 `LLM_PROVIDER` 设为 `anthropic` |

### 2. 配置仓库 Variables（同一页面的 *Variables* 标签，均可选）

| 名称 | 默认值 | 说明 |
|---|---|---|
| `MAIL_TO` | `aa1928@gmail.com` | 收件人，多个用逗号分隔 |
| `LLM_PROVIDER` | 自动 | `gemini` / `anthropic` / `none` |
| `GEMINI_BASE_URL` | 官方地址 | **可填本仓库部署的 Deno 反代地址** `https://<你的项目名>.deno.dev`，解决 Gemini 访问问题 |
| `GEMINI_MODEL` | `gemini-2.5-flash` | 也可用 `gemini-2.5-pro`（分析更深，成本更高） |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | |

### 3. 启用并首次运行

1. 代码已在默认分支（`main`）。该工作流仅支持手动触发（定时任务由 Routine 承担，避免重复运行冲突）。
2. 进入 Actions → "民族学学科监测周报" → *Run workflow* 手动触发一次（可勾选"只生成报告，不发送邮件"先看效果）。
3. 运行结束后在该次运行页面下载 artifact `ethno-monitor-<n>`：包含 `reports/latest.md`、HTML 报告、`debug/` 下各数据源的原始页面快照。若某数据源状态为 ❌ 或条目为 0，用快照对照 `config/sources.yaml` 调整 URL / 正则即可，无需改代码。
4. 报告与状态会自动提交到 `reports/`、`data/state.json` 与 `docs/`。

> 首次运行会把当前窗口内的全部条目视为"新增"；之后每周只报告 `data/state.json` 中未出现过的条目。

## 三、本地运行

```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # 自检
python -m ethno_monitor demo              # 示例数据跑通全流程，输出到 reports/demo/
python -m ethno_monitor collect --only 社科办   # 调试单个数据源（名称包含该字符串）
export GEMINI_API_KEY=... SMTP_HOST=smtp.qq.com SMTP_PORT=465 SMTP_USER=... SMTP_PASS=...
python -m ethno_monitor test-email        # 验证邮箱配置
python -m ethno_monitor run --no-email    # 真实采集 + 分析，不发邮件
python -m ethno_monitor run               # 完整运行
python -m ethno_monitor collect --out c.json                      # 采集结果落盘
python -m ethno_monitor prompt --items-file c.json --items-file extra.json   # 导出分析提示词（供 Claude 会话撰写分析）
python -m ethno_monitor run --no-llm --no-email --items-file extra.json --analysis-file analysis.md   # 用外部条目与分析生成周报
python -m ethno_monitor site              # 仅重建 docs/ 观察站网页
```

## 四、配置文件

| 文件 | 作用 |
|---|---|
| `config/sources.yaml` | 期刊列表与目录页、公告类来源（URL、链接正则、日期正则、过滤关键词）、国家社科基金数据库参数、下钻规则、RSS、LLM 检索查询词、监测窗口 `lookback_days` |
| `config/keywords.yaml` | 四方向分类关键词及权重、民族学相关性关键词、广西相关性关键词 |
| `config/guangxi.yaml` | 广西区域知识库（定位、十二个世居民族、南岭走廊、东南亚民族研究、文化符号、政策语境、研究机构）与规则兜底选题库 |

常见调整：
- **新增期刊**：在 `journals` 追加 `name/aliases/toc_pages`；LLM 联网检索会自动逐刊查询。
- **新增公告来源**：在 `notice_sources` 追加一项，填列表页 URL、`link_regex`、`url_date_regex`、`include_keywords`。
- **调整方向归类**：修改 `keywords.yaml` 中的关键词权重；`priority` 决定同分时的优先方向。
- **调整选题风格**：修改 `guangxi.yaml` 的知识库条目或 `ethno_monitor/analysis.py` 中的提示词。

## 五、周报结构

1. **本周概览**：论文/课题/公告/涉桂/待核实数量，四方向分布
2. **论文监测（按方向）**：题目、作者、期刊期号、标记（🌿桂 涉桂 / ⚠未核实）、来源链接
3. **课题立项监测（按资助机构）**：课题、负责人、单位、类别、方向；相关公告及下钻结果
4. **研究分析与广西特色选题策划**（LLM）：总评 → 四方向分述 → 立项态势与申报启示 → **12 个广西特色选题表**（题目 / 方向 / 依据 / 广西切入点 / 拟投期刊或项目类别）→ 精读建议 → 下周关注
5. **数据源状态**：每个来源成功与否、条目数、说明、耗时

## 六、已知限制与注意事项

- **数据源可达性**：知网等站点有较强反爬；部分政府网站会限制境外 IP（GitHub Actions 运行于境外）。系统对每个来源独立容错，并靠"国家哲学社会科学文献中心 + LLM 联网检索"兜底。若长期某来源失败，可在 `sources.yaml` 中替换为其他镜像页或 RSS。
- **站点结构**：采集器按各站常见结构编写并配备单元测试，但开发环境无法直连这些站点实测。首次运行请务必查看 artifact 中的 `debug/` 快照与"数据源状态"表，按需微调选择器/正则。
- **LLM 条目的可信度**：由联网检索得到、但无来源链接支撑的条目标记 ⚠未核实，引用前请到知网/期刊官网核对；分析提示词已禁止编造监测数据之外的论文与人名。
- **成本**：默认 `gemini-2.5-flash`，每周约 20 次联网检索 + 1 次长文分析，费用极低；可通过 `llm_research.max_queries` 控制。
- **邮件被拦截**：QQ 邮箱对陌生发件人较严格，建议用自己的 QQ 邮箱 SMTP 发给自己；若进入垃圾箱，将发件人加入白名单。
