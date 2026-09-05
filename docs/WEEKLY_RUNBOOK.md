# 每周自动运行手册（供 Claude Routine 会话执行）

> 本手册是每周一自动会话的操作规程。会话按步骤执行，遇到某步失败要记录原因并继续后续步骤，最终必须产出报告并推送到 Gmail。

## 0. 准备
```bash
cd /home/user/cfll-gemini 2>/dev/null || git clone https://github.com/BenHaoz/cfll-gemini /home/user/cfll-gemini && cd /home/user/cfll-gemini
git checkout main && git pull --ff-only origin main
pip install -q -r requirements.txt
mkdir -p /tmp/em && export TODAY=$(date +%F)
```

## 1. 读取 GitHub Actions 的采集结果
GitHub Actions 工作流「民族学监测·每周采集」在每周一 06:30（北京时间）已把采集结果提交到 `data/collected/latest.json`（含条目与各数据源状态）。
```bash
cp data/collected/latest.json /tmp/em/collected.json
python - <<'PY'
import json; d=json.load(open('/tmp/em/collected.json'))
print(len(d['items']),'items'); [print('OK ' if s['ok'] else 'ERR', s['name'], s['count'], s['message'][:80]) for s in d['statuses']]
PY
```
若该文件不存在或早于 3 天，可用 GitHub MCP 工具 `actions_run_trigger` 触发一次工作流 `weekly-collect.yml` 并等待约 5 分钟后 `git pull` 重试；若仍无结果，则以空采集继续（本环境自身无法直连国内站点）：
```bash
[ -f /tmp/em/collected.json ] || echo '{"items":[],"statuses":[]}' > /tmp/em/collected.json
```

## 2. 联网补充检索（会话自己用 WebSearch 完成，是本环境下的主要数据来源）
目标：过去 14 天内新出现的条目。
- **期刊目录**：对 `config/sources.yaml` 中 10 种期刊，各搜索 2–3 次「《刊名》2026年第N期 目录」「刊名 2026 最新一期 文章」等，记录搜索结果摘要里**实际出现**的文章标题、作者、期号与来源链接。
- **课题立项**：搜索「2026 国家社科基金 立项名单 民族学」「铸牢中华民族共同体意识研究专项 立项」「国家民委民族研究项目 2026年度 立项」「教育部 重大课题攻关 2026 民族」「广西民族大学/广西师范大学 2026 国家社科基金 立项 民族」等。
- **铁律**：绝不编造标题、作者、课题、人名；无来源链接的条目 `verified=false`。
- 写入 `/tmp/em/extra_items.json`，JSON 数组，元素格式：
```json
{"kind":"paper|project|notice","title":"...","url":"来源链接","source":"期刊名或资助机构","date":"YYYY-MM-DD 或 YYYY-MM","authors":["..."],"affiliation":"单位","verified":true,"evidence":["来源链接"],"extra":{"issue":"2026年第4期","funder":"国家社科基金","project_type":"一般项目","pi":"负责人","from_notice":"公告标题","summary":"一句话主题","via":"websearch"}}
```

## 3. 生成分析提示词并撰写分析
```bash
python -m ethno_monitor prompt --items-file /tmp/em/collected.json --items-file /tmp/em/extra_items.json --date $TODAY > /tmp/em/prompt.txt
```
阅读 `/tmp/em/prompt.txt`（含本周新增条目摘要、四方向定义、广西知识库和写作要求），**由会话自己撰写**六节分析 Markdown（总评 / 四方向分述 / 立项态势与申报启示 / 12 个广西特色选题表 / 精读建议 / 下周关注），保存为 `/tmp/em/analysis.md`。要求：只引用监测数据中的条目；选题须为可直接投稿/申报的主副标题结构，并写明广西切入点与拟投期刊或项目类别。

## 4. 生成周报、网页并提交
```bash
python -m ethno_monitor run --no-llm --no-email --collected-file /tmp/em/collected.json --items-file /tmp/em/extra_items.json --analysis-file /tmp/em/analysis.md --date $TODAY | tee /tmp/em/run.json
git add reports data/state.json docs
git -c user.name="ethno-monitor" -c user.email="ethno-monitor@users.noreply.github.com" commit -m "chore(report): 民族学监测周报 $TODAY" || true
git push origin main
```
观察站网页：`docs/index.html`；Artifact 版本为 `docs/observatory.artifact.html`，用 Artifact 工具以 `url: https://claude.ai/code/artifact/4deee0c5-bc00-4d00-9aec-c5511a4786fc` 重新发布（保持同一链接）；若仓库已开启 GitHub Pages（main 分支 /docs），地址为 https://benhaoz.github.io/cfll-gemini/ 。

## 5. 推送到 Gmail
用 Gmail 连接器 `send_message` 发送到 **aa1928@gmail.com**：
- 主题：`【民族学学科监测周报】YYYY年第NN周：新增论文X篇 / 立项Y项`
- `htmlBody`：`reports/latest.md` 对应的 HTML（`reports/<slug>.html` 文件内容，去掉 `<!DOCTYPE>`/`<html>`/`<head>` 外壳只保留 `<style>` 与 `<body>` 内容亦可）
- `body`：`reports/latest.md` 的纯文本
- 附件：`reports/<slug>.md`（text/markdown，base64）
- 正文开头加一行观察站网页链接：https://claude.ai/code/artifact/4deee0c5-bc00-4d00-9aec-c5511a4786fc

## 6. 收尾
在会话最后用中文简要汇报：新增条目数、数据源成功/失败情况、邮件是否发送成功、报告提交的 commit。若邮件发送失败，重试一次；仍失败则在汇报中说明原因。
