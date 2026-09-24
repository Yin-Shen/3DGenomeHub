# 架构设计 (v3)

3DGenomeHub 是一个自动更新、经过相关性过滤的 3D 基因组 × 深度学习文献库。
所有代码位于 `src/genome_literature/`，数据保存在 `papers/`，生成的文档位于 `README.md` 与 `docs/papers/`。

## 数据流

```
SEARCH_TOPICS (config.py)
   │  按数据库语法生成检索式 (PubMed [tiab] / Europe PMC TITLE+ABSTRACT / arXiv ti+abs / 自由文本)
   ▼
fetcher.py ── PubMed · Europe PMC(含 bioRxiv/medRxiv 预印本) · bioRxiv 近期全量扫描 · arXiv · Semantic Scholar · CrossRef
   │  net.py：按主机限速、429/5xx 重试退避；单个数据源失败只记录，不中断
   ▼
records.py ── 统一字段、清洗 HTML/JATS、DOI/PMID/arXiv/标题跨库去重，预印本与正式发表版本合并
   ▼
relevance.py ── 3D 基因组证据打分（必须命中核心术语）+ 负面词惩罚 + AI/ML 打分 → track / relevance / dl_methods / tools
   ▼
categorizer.py ── 19 个主题，带权重、词边界、标题加倍；每篇最多 3 个主题
   ▼
storage.py ── papers/papers.json（数据库）· papers/state.json（各数据源上次成功日期、上次新增 ID）
   ▼
translator.py ── 新论文标题/摘要的中文学术翻译 → papers/translations.json（未配置 TRANSLATE_API_KEY 时跳过）
   ▼
readme_generator.py (README.md + docs/papers/*.md) · summarizer.py + email_notifier.py (邮件摘要) · web_app.py (本地 GUI) · cli.py
```

## 关键设计

| 问题 | 做法 |
| --- | --- |
| 检索结果大量无关 | 每条候选记录都要经过 `relevance.is_relevant`：至少一个核心 3D 基因组术语（Hi-C、TAD、chromatin loop…），加权得分 ≥ `MIN_GENOME_SCORE`；Hi-C 基因组组装 scaffolding、蛋白质 contact map、转录激活结构域 (TAD)、HIC 色谱等同形词会被扣分 |
| 关键词子串误匹配（gan⊂organization, tad⊂metadata） | `matching.py`：整词匹配；全大写缩写区分大小写；连字符/空格/复数自动兼容；`re:` 前缀写正则 |
| 同一论文多次出现 | DOI、PMID、arXiv ID、标准化标题任一相同即合并；保留最早的 `id` 与 `first_seen`，合并摘要/引用数/来源 |
| bioRxiv 没有检索 API | Europe PMC 的预印本索引 (`SRC:PPR`) 做主题检索 + bioRxiv details API 对近期窗口全量扫描并预过滤 |
| 每次都“全部是新论文” | 数据库提交到仓库；增量模式按各数据源上次成功日期回溯 `INCREMENTAL_OVERLAP_DAYS` 天 |
| 经典论文缺失 | 首次运行（或 `--backfill`）按相关性排序检索全部年份；`papers/curated_dois.txt` 保证里程碑论文被收录 |
| 规则调整后旧数据不一致 | 每次运行都会对全库重新打分、分类，不再满足条件的记录被移除；也可 `python -m genome_literature rebuild` |

## 中文学术翻译

`translator.py` 调用任意 OpenAI 兼容的 chat-completions 接口（默认 DeepSeek，可换通义千问、Moonshot 或本地部署模型），
通过 `.env` 中的 `TRANSLATE_API_KEY`、`TRANSLATE_API_BASE`、`TRANSLATE_MODEL` 配置。为保证译文准确：

1. **术语表约束**：`GLOSSARY` 收录 3D 基因组、表观遗传与深度学习常用术语（如 topologically associating domain → 拓扑关联结构域、
   loop extrusion → 环挤出、cohesin → 黏连蛋白），论文中出现的术语随请求一并发送，并在译文中逐条核验。
2. **确定性输出**：temperature = 0，要求只输出 JSON（`title_zh`、`abstract_zh`），系统提示规定忠实完整、不增删、
   结构化摘要小标题统一为“背景：/方法：/结果：/结论：”，术语参照全国科学技术名词审定委员会规范。
3. **自动校验**：原文中的缩写、基因/蛋白/工具名（CTCF、Hi-C、C.Origami…）与全部数值必须原样出现在译文中；
   术语须按术语表翻译；译文须为中文且长度比例合理（识别漏译、增译）。
4. **纠错重译**：校验未通过时把问题逐条反馈给模型重译一次；仍未通过的译文标记 `needs_review`，
   在网页中显示“译文待校对”并列出具体问题。
5. **缓存与人工校对**：译文按论文 `id` 与原文哈希缓存在 `papers/translations.json`，原文变化后自动失效；
   人工修改后将该条目的 `"reviewed"` 设为 `true`，此后不会被覆盖。

使用方式：网页中勾选“中英对照”、点击“翻译本页”或单篇论文的“中文翻译”；命令行
`python -m genome_literature translate [--ml] [--new] [--id ID] [-n 50] [--all] [--force]`，
`python -m genome_literature translate-text "标题" "摘要"` 可单独测试一段文字；`run-pipeline` 会自动翻译新增论文
（`TRANSLATE_NEW_PAPERS=0` 关闭，`TRANSLATE_MAX_PER_RUN` 控制每次上限）。

## 调整方法

- **扩大/缩小检索范围**：编辑 `config.SEARCH_TOPICS`（组内 OR、组间 AND）。
- **收紧/放宽收录标准**：调整 `MIN_GENOME_SCORE`、`GENOME_CORE_TERMS`、`GENOME_CONTEXT_TERMS`、`NEGATIVE_TERMS`。
- **修改主题**：编辑 `config.CATEGORIES` 中各主题的 `terms` 权重；`title_only` 表示只看标题。
- 修改后运行 `rebuild` 重新打分并重新生成 README，再运行 `python -m pytest` 确认测试通过。

## 自动化

- `.github/workflows/update.yml`：每周一运行增量更新，提交 `papers/`、`README.md`、`docs/papers/`；手动触发时可勾选 backfill。
- `.github/workflows/ci.yml`：在 Python 3.9 与 3.12 上运行测试。
- 可选 Secrets：`NCBI_API_KEY`、`NCBI_EMAIL`、`SEMANTIC_SCHOLAR_API_KEY`、`SMTP_*`、`EMAIL_FROM`、`EMAIL_RECIPIENTS`、
  `TRANSLATE_API_KEY`、`TRANSLATE_API_BASE`、`TRANSLATE_MODEL`（配置后每周更新会自动翻译新论文）。
