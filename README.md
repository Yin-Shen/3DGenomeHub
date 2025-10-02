# 3DGenomeHub

3DGenomeHub is an opinionated starter kit for building an approachable knowledge
base around 3D genome science. It curates beginner-friendly explainers,
self-paced courses, interactive activities, and research primers so that new
practitioners can build confidence before diving into primary literature.

## Key Features

- 📚 **Beginner-first curation**: English-language resources designed for adult
  learners and early-career scientists who are new to spatial genomics.
- 🔎 **Built-in semantic search**: TF–IDF retrieval with extensible embedding
  hooks so you can plug in vector databases or LLM rerankers later.
- 🌐 **Web workspace**: FastAPI-powered web app with search, filtering, and a
  one-click "Update knowledge base" workflow.
- 🧪 **Data pipelines**: YAML import/export templates, ingestion utilities, and
  a refresh pipeline that aggregates the latest open-access literature.
- 🛠️ **CLI & API**: Typer command line helpers and documented REST endpoints for
  automation or integration into other tools.

## Quick Start

### 1. Set up the environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Build the sample knowledge base

```bash
three-d-genome-hub ingest data/sample-data.yml --database data/knowledge_base.db
three-d-genome-hub build-index --database data/knowledge_base.db --output data/artifacts/vector_index.pkl
```

### 3. Launch the web workspace

```bash
uvicorn three_d_genome_hub.api.server:app --reload --port 8000
```

Visit `http://localhost:8000/` to use the search interface or explore the API
schema at `http://localhost:8000/docs`.

## Project Structure

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

## Content Types

The curated dataset focuses on three pillars that support beginners:

- **Foundations** – explainer articles, glossaries, podcasts, and hands-on
  activities that introduce core vocabulary and concepts.
- **Data-Exploration** – tutorials, workshops, and practical checklists for
  working with Hi-C and other 3D genomics data products.
- **Research-Summaries** – accessible overviews of influential papers and
  perspectives that keep learners informed without demanding deep expertise.

> Tip: extend `data/sample-data.yml` with your own entries or connect
> `pipelines/update.py` to additional APIs (e.g., Crossref, arXiv, bioRxiv).

## Roadmap

- [x] Provide beginner-centric curation and sample data.
- [x] Ship TF–IDF retrieval, REST API, and a searchable web workspace.
- [ ] Integrate a vector database (Qdrant, Milvus) for large-scale semantic
      search.
- [ ] Pair the knowledge base with LLM-powered copilots for Q&A and content
      authoring.
- [ ] Add data visualizations such as timelines and knowledge graphs.

## Contributing

We welcome pull requests that add resources, improve the update pipeline, or
expand the web workspace. To contribute:

1. Fork the repository and create a topic branch.
2. Add or update documentation, data, or code.
3. Run the available CLI/API smoke tests.
4. Open a pull request detailing your changes and validation steps.

## License

Released under the MIT License. You are free to use, remix, and share the
knowledge base for educational or research purposes.
