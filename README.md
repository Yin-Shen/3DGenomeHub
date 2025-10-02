# 3DGenomeHub

3DGenomeHub 是一个面向三维基因组研究的开箱即用知识库项目，聚合了基础教育资源、科研综述以及机器学习/深度学习在三维基因组领域的算法论文、工具与数据集。项目旨在帮助初学者（含小学、初中阶段）和科研人员快速获取可复用的知识资产，并提供构建 AI 驱动问答与检索的参考实现。

## 功能概览

- 📚 **分层知识结构**：面向低年级学生的科普课程、进阶学习单元与研究综述。
- 🧠 **AI 检索能力**：基于 TF-IDF 的语义检索示例，可扩展至大语言模型与向量数据库。
- 🧪 **研究资源汇总**：整理机器学习/深度学习算法在三维基因组中的经典论文、开源工具与数据集。
- 🛠️ **数据构建流水线**：提供数据标注模板、批量导入脚本以及索引构建流程。
- 🌐 **API 与 CLI**：FastAPI 服务用于知识检索，Typer CLI 支持数据导入、索引重建与导出。

## 快速开始

### 1. 克隆与安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 构建示例知识库

```bash
three-d-genome-hub ingest data/sample-data.yml --database data/knowledge_base.db
three-d-genome-hub build-index --database data/knowledge_base.db --output data/artifacts/vector_index.pkl
```

### 3. 启动 API 服务

```bash
uvicorn three_d_genome_hub.api.server:app --reload --port 8000
```

启动后访问 `http://localhost:8000/docs` 体验交互式文档。也可使用 CLI 查询：

```bash
three-d-genome-hub query "什么是三维基因组？"
```

## 项目结构

```text
├── README.md
├── requirements.txt
├── pyproject.toml
├── data
│   ├── sample-data.yml
│   └── artifacts/
├── docs
│   ├── architecture.md
│   ├── curriculum.md
│   ├── data_governance.md
│   └── roadmap.md
└── src
    └── three_d_genome_hub
        ├── __init__.py
        ├── api/
        │   └── server.py
        ├── ingestion/
        │   ├── loader.py
        │   └── schema.py
        ├── pipelines/
        │   ├── build_index.py
        │   └── curate.py
        ├── utils/
        │   ├── embeddings.py
        │   └── logging.py
        ├── cli.py
        ├── config.py
        ├── knowledge_base.py
        └── models.py
```

## 数据来源与内容类型

项目提供 `data/sample-data.yml` 示例，涵盖以下类别：

- **Foundations**：面向低年级学生的科普课程与实验活动。
- **Advanced-Topics**：围绕染色质高级结构、Hi-C 技术及其分析的资源。
- **ML-DL-Research**：收录深度学习和机器学习方法（如 Graph Neural Networks、Transformers、Diffusion 模型）在三维基因组的代表性论文。

> **提示**：可根据模板扩展更多条目，或使用 `ingestion/curate.py` 中的脚本接入外部数据源（如 CrossRef、arXiv API）。

## 开发路线图

- [x] 提供分层知识结构与样例数据
- [x] 构建 TF-IDF 检索索引与 API
- [ ] 集成向量数据库（如 Qdrant、Milvus）支持更大规模语义检索
- [ ] 联合 LLM（OpenAI、DeepSeek 等）构建问答助手与课程生成工具
- [ ] 构建可视化前端（Timeline、知识图谱）

## 贡献指南

欢迎通过 Issue/PR 扩充资料、改进算法与教学内容。可遵循以下步骤：

1. Fork 本仓库并创建新分支
2. 编写或更新文档/代码
3. 运行 `pytest`（未来支持）或手动测试 CLI/API
4. 提交 PR，描述改动范围与测试情况

## 许可证

项目在 MIT License 下发布。欢迎自由使用与分发。
