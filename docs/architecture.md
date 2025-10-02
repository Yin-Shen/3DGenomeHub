# 架构设计概览

3DGenomeHub 采用模块化架构，将内容治理、数据存储、检索服务与 AI 能力解耦，便于后续扩展。

## 核心组件

| 模块 | 说明 | 关键技术 |
| --- | --- | --- |
| 数据模板 (YAML) | 统一三维基因组知识条目的结构 | YAML, Pydantic |
| 数据导入 (Ingestion) | 校验、清洗并写入 SQLite/Parquet | Typer CLI, Pandas |
| 索引构建 | 生成 TF-IDF 向量索引，支持语义检索 | scikit-learn |
| API 服务 | 暴露 RESTful 检索接口和可视化文档 | FastAPI |
| AI 扩展 | 预留 LLM 推理接口、向量数据库适配层 | LangChain (可选), Qdrant/Milvus |

## 数据流

1. **采集**：从 `data/sample-data.yml` 或外部数据源生成标准化 YAML/JSON。
2. **导入**：执行 `three-d-genome-hub ingest` 将数据写入 `data/knowledge_base.db`。
3. **索引**：运行 `three-d-genome-hub build-index` 生成 `data/artifacts/vector_index.pkl`。
4. **服务**：启动 `uvicorn`，API 自动加载数据库与索引，完成问答/检索。

## 扩展建议

- 引入 `celery + redis` 处理大规模爬虫与数据清洗。
- 替换 TF-IDF 为 `sentence-transformers` 或自研模型，构建高质量语义检索。
- 构建知识图谱：利用 NetworkX/Neo4j 建立实体关系（基因、组织、实验技术）。
- 打通教学系统：通过 LTI 或 REST API 与 LMS（如 Moodle）集成。
