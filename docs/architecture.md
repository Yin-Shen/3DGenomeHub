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

## 调整方法

- **扩大/缩小检索范围**：编辑 `config.SEARCH_TOPICS`（组内 OR、组间 AND）。
- **收紧/放宽收录标准**：调整 `MIN_GENOME_SCORE`、`GENOME_CORE_TERMS`、`GENOME_CONTEXT_TERMS`、`NEGATIVE_TERMS`。
- **修改主题**：编辑 `config.CATEGORIES` 中各主题的 `terms` 权重；`title_only` 表示只看标题。
- 修改后运行 `rebuild` 重新打分并重新生成 README，再运行 `python -m pytest` 确认测试通过。

## 自动化

- `.github/workflows/update.yml`：每周一运行增量更新，提交 `papers/`、`README.md`、`docs/papers/`；手动触发时可勾选 backfill。
- `.github/workflows/ci.yml`：在 Python 3.9 与 3.12 上运行测试。
- 可选 Secrets：`NCBI_API_KEY`、`NCBI_EMAIL`、`SEMANTIC_SCHOLAR_API_KEY`、`SMTP_*`、`EMAIL_FROM`、`EMAIL_RECIPIENTS`。
